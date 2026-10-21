from django import forms
from django.forms import BaseFormSet, formset_factory
from django.utils import timezone

from .models import GodownStockReceipt

from products.models import Product


def active_products_for_group(group):
    """Return active products in the same category-first order as the stock UI."""
    products = list(Product.objects.filter(group=group, active=True).select_related("category"))
    category_order = {
        category_id: index
        for index, category_id in enumerate(
            Product.objects.filter(group=group).values_list("category_id", flat=True).distinct()
        )
    }
    return sorted(products, key=lambda product: (category_order.get(product.category_id, len(category_order)), product.name.lower()))


def product_choices_for_group(group, products):
    return [("", "Select product")] + [
        (category.name, [(product.pk, product.name) for product in products if product.category_id == category.id])
        for category in group.categories.filter(active=True)
        if any(product.category_id == category.id for product in products)
    ]


class GodownStockReceiptForm(forms.ModelForm):
    class Meta:
        model = GodownStockReceipt
        fields = ("product", "received_at", "received_ctn", "received_pcs", "reference", "notes")
        widgets = {
            "received_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "received_ctn": forms.NumberInput(attrs={"min": 0, "step": 1}),
            "received_pcs": forms.NumberInput(attrs={"min": 0, "step": 1}),
            "reference": forms.TextInput(attrs={"placeholder": "Company, challan, or reference"}),
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Optional note"}),
        }

    def __init__(self, *args, group=None, **kwargs):
        super().__init__(*args, **kwargs)
        products = active_products_for_group(group)
        self.fields["product"].queryset = Product.objects.filter(pk__in=[product.pk for product in products])
        self.fields["product"].choices = product_choices_for_group(group, products)
        self.fields["received_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        if not self.is_bound:
            self.initial["received_at"] = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "godown-input")


class BulkStockReceiptDetailsForm(forms.Form):
    received_at = forms.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "class": "godown-input"}, format="%Y-%m-%dT%H:%M"),
    )
    reference = forms.CharField(
        required=True,
        max_length=160,
        widget=forms.TextInput(attrs={"class": "godown-input", "placeholder": "Enter challan or reference number"}),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "godown-input", "rows": 3, "placeholder": "Optional note"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial["received_at"] = timezone.localtime().strftime("%Y-%m-%dT%H:%M")


class BulkStockReceiptRowForm(forms.Form):
    product = forms.ModelChoiceField(queryset=Product.objects.none(), required=False)
    received_ctn = forms.IntegerField(min_value=0, required=False, initial=0)
    received_pcs = forms.IntegerField(min_value=0, required=False, initial=0)

    def __init__(self, *args, group=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_empty_row = False
        products = active_products_for_group(group)
        self.fields["product"].queryset = Product.objects.filter(pk__in=[product.pk for product in products])
        self.fields["product"].choices = product_choices_for_group(group, products)
        self.fields["product"].widget.attrs.update({"class": "godown-input", "data-field": "product", "aria-label": "Product"})
        self.fields["received_ctn"].widget.attrs.update({"class": "godown-input", "data-field": "received_ctn", "aria-label": "CTN quantity"})
        self.fields["received_pcs"].widget.attrs.update({"class": "godown-input", "data-field": "received_pcs", "aria-label": "PCS quantity"})

    def clean(self):
        cleaned_data = super().clean()
        product = cleaned_data.get("product")
        received_ctn = cleaned_data.get("received_ctn")
        received_pcs = cleaned_data.get("received_pcs")

        raw_product = str(self.data.get(self.add_prefix("product"), "")).strip() if self.is_bound else ""
        raw_ctn = str(self.data.get(self.add_prefix("received_ctn"), "")).strip() if self.is_bound else ""
        raw_pcs = str(self.data.get(self.add_prefix("received_pcs"), "")).strip() if self.is_bound else ""

        ctn_val = received_ctn if received_ctn is not None else 0
        pcs_val = received_pcs if received_pcs is not None else 0

        has_product = bool(product or raw_product)
        has_qty = (ctn_val > 0) or (pcs_val > 0) or (raw_ctn not in ("", "0")) or (raw_pcs not in ("", "0"))

        # Completely empty row (no product and no quantity) -> ignore safely
        if not has_product and not has_qty:
            self.is_empty_row = True
            self._errors.clear()
            cleaned_data["received_ctn"] = 0
            cleaned_data["received_pcs"] = 0
            return cleaned_data

        self.is_empty_row = False

        # Quantity entered but no product selected
        if not product and has_qty:
            if not self.errors.get("product"):
                self.add_error("product", "Please select a product for every stock-entry row containing a quantity.")
            return cleaned_data

        # Product selected but quantity missing or invalid
        if product:
            if received_ctn is None and raw_ctn != "0":
                self.add_error("received_ctn", "Please enter a valid carton quantity.")
            if received_pcs is None and raw_pcs != "0":
                self.add_error("received_pcs", "Please enter a valid piece quantity.")

            if ctn_val == 0 and pcs_val == 0 and not self.errors.get("received_ctn") and not self.errors.get("received_pcs"):
                self.add_error("received_ctn", "Enter at least one carton or one piece.")
            elif received_pcs is not None and received_pcs >= product.ctn_size:
                self.add_error("received_pcs", "Partial pieces must be smaller than this product's Pieces per CTN value.")

        cleaned_data["received_ctn"] = ctn_val
        cleaned_data["received_pcs"] = pcs_val
        return cleaned_data


class BaseBulkStockReceiptFormSet(BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return

        products = {}
        has_valid_row = False
        for form in self.forms:
            if getattr(form, "is_empty_row", False):
                continue

            product = form.cleaned_data.get("product")
            if not product:
                continue

            has_valid_row = True
            duplicate = products.get(product.pk)
            if duplicate is not None:
                message = "This product is already included in another row."
                duplicate.add_error("product", message)
                form.add_error("product", message)
            else:
                products[product.pk] = form

        if not any(self.errors) and not has_valid_row:
            raise forms.ValidationError("Please add at least one product with a valid quantity.")


BulkStockReceiptFormSet = formset_factory(
    BulkStockReceiptRowForm,
    formset=BaseBulkStockReceiptFormSet,
    extra=1,
    min_num=0,
    validate_min=False,
)
