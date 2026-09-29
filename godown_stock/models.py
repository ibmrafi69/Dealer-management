from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from products.models import Product


class GodownStockReceipt(models.Model):
    """A persistent company-stock receipt. Current stock is derived, never saved."""

    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name="godown_stock_receipts")
    product_id_snapshot = models.BigIntegerField(null=True, blank=True, editable=False)
    product_name_snapshot = models.CharField(max_length=160, blank=True)
    category_snapshot = models.CharField(max_length=20, blank=True)
    ctn_size_snapshot = models.PositiveIntegerField(default=1)
    received_at = models.DateTimeField(default=timezone.now)
    received_ctn = models.PositiveIntegerField(default=0)
    received_pcs = models.PositiveIntegerField(default=0)
    total_pieces = models.PositiveIntegerField(editable=False)
    reference = models.CharField(max_length=160, blank=True, help_text="Company, challan, or reference number")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["received_at", "created_at", "pk"]

    def clean(self):
        errors = {}
        if not self.received_ctn and not self.received_pcs:
            errors["received_ctn"] = "Enter at least one carton or one piece."
        if self._state.adding and not self.product_id:
            errors["product"] = "Select an active product from Product Setup."
        if self.product_id and self.received_pcs >= self.product.ctn_size:
            errors["received_pcs"] = "Partial pieces must be smaller than this product's Pieces per CTN value."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.product_id:
            product = self.product
            if self._state.adding:
                self.product_id_snapshot = product.pk
                self.product_name_snapshot = product.name
                self.category_snapshot = product.category
                self.ctn_size_snapshot = product.ctn_size
            self.total_pieces = self.received_ctn * product.ctn_size + self.received_pcs
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product_name_snapshot or self.product} receipt - {self.total_pieces} PCS"
