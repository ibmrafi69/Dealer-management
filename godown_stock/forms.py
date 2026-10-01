from django import forms
from django.utils import timezone

from .models import GodownStockReceipt

from products.models import Product


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
        products = list(Product.objects.filter(group=group, active=True))
        category_order = {category_id: index for index, category_id in enumerate(Product.objects.filter(group=group).values_list("category_id", flat=True).distinct())}
        products.sort(key=lambda product: (category_order.get(product.category_id, len(category_order)), product.name.lower()))
        self.fields["product"].queryset = Product.objects.filter(pk__in=[product.pk for product in products])
        self.fields["product"].choices = [("", "Select product")] + [
            (category.name, [(product.pk, product.name) for product in products if product.category_id == category.id])
            for category in group.categories.filter(active=True)
            if any(product.category_id == category.id for product in products)
        ]
        self.fields["received_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        if not self.is_bound:
            self.initial["received_at"] = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "godown-input")
