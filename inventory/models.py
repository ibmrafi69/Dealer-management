from django.db import models

from dealers.models import Dealer
from products.models import Product


class Damage(models.Model):
    date = models.DateField()
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="damages")
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    value = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    reason = models.CharField(max_length=255, blank=True)
    related_transaction = models.ForeignKey(
        "sales.SalesTransaction", on_delete=models.SET_NULL, null=True, blank=True, related_name="damages"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.quantity < 0:
            raise ValueError("Damage quantity cannot be negative.")
        # Damage recorded against an invoice must retain that invoice's sale
        # price, even after the product price is changed in Product Setup.
        # Standalone inventory damage retains the existing dealer-price rule.
        price = self.product.dealer_price
        if self.related_transaction_id:
            item = self.related_transaction.items.filter(product_id=self.product_id).only("sale_price_snapshot").first()
            if item:
                price = item.sale_price_snapshot
        self.value = self.quantity * price
        return super().save(*args, **kwargs)


class StockTransaction(models.Model):
    PURCHASE = "PURCHASE"
    SALE = "SALE"
    RETURN = "RETURN"
    DAMAGE = "DAMAGE"
    ADJUSTMENT = "ADJUSTMENT"
    TRANSACTION_TYPES = (
        (PURCHASE, "Purchase"),
        (SALE, "Sale"),
        (RETURN, "Return"),
        (DAMAGE, "Damage"),
        (ADJUSTMENT, "Adjustment"),
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="stock_transactions")
    dealer = models.ForeignKey(Dealer, on_delete=models.PROTECT, null=True, blank=True, related_name="stock_transactions")
    date = models.DateField()
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    @classmethod
    def record_sale_item(cls, item):
        if item.sale_quantity:
            return cls.objects.create(
                product=item.product,
                dealer=item.transaction.dealer,
                date=item.transaction.date,
                transaction_type=cls.SALE,
                quantity=-item.sale_quantity,
                reference=item.transaction.invoice_number,
            )
        return None

    @classmethod
    def record_return_item(cls, item):
        if item.return_quantity:
            return cls.objects.create(
                product=item.product,
                dealer=item.transaction.dealer,
                date=item.transaction.date,
                transaction_type=cls.RETURN,
                quantity=item.return_quantity,
                reference=item.transaction.invoice_number,
            )
        return None

    @classmethod
    def record_damage(cls, damage):
        return cls.objects.create(
            product=damage.product,
            dealer=damage.related_transaction.dealer if damage.related_transaction else None,
            date=damage.date,
            transaction_type=cls.DAMAGE,
            quantity=-damage.quantity,
            reference=damage.related_transaction.invoice_number if damage.related_transaction else "",
        )
