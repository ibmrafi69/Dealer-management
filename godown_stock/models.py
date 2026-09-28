from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from products.models import Product


class GodownStockReceipt(models.Model):
    """A persistent company-stock receipt. Current stock is derived, never saved."""

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="godown_stock_receipts")
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
        if self.product_id and self.received_pcs >= self.product.ctn_size:
            errors["received_pcs"] = "Partial pieces must be smaller than this product's Pieces per CTN value."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.product_id:
            self.total_pieces = self.received_ctn * self.product.ctn_size + self.received_pcs
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product} receipt - {self.total_pieces} PCS"
