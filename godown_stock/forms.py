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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        products = list(Product.objects.filter(active=True))
        category_order = {category: index for index, category in enumerate(Product.CATEGORY_ORDER)}
        products.sort(key=lambda product: (category_order[product.category], product.name.lower()))
        self.fields["product"].queryset = Product.objects.filter(pk__in=[product.pk for product in products])
        self.fields["product"].choices = [("", "Select product")] + [
            (
                category,
                [(product.pk, product.name) for product in products if product.category == category],
            )
            for category in Product.CATEGORY_ORDER
            if any(product.category == category for product in products)
        ]
        self.fields["received_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        if not self.is_bound:
            self.initial["received_at"] = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "godown-input")
