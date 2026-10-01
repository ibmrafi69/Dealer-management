from django.db import models

from dealers.models import Dealer
from dealers.models import Group
from products.models import Product


class Damage(models.Model):
    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="damages")
    date = models.DateField()
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name="damages")
    product_id_snapshot = models.BigIntegerField(null=True, blank=True, editable=False)
    product_name_snapshot = models.CharField(max_length=160, blank=True)
    category_snapshot = models.CharField(max_length=20, blank=True)
    ctn_size_snapshot = models.PositiveIntegerField(default=1)
    unit_price_snapshot = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    value = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    reason = models.CharField(max_length=255, blank=True)
    related_transaction = models.ForeignKey(
        "sales.SalesTransaction", on_delete=models.SET_NULL, null=True, blank=True, related_name="damages"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.group_id:
            self.group = self.related_transaction.group if self.related_transaction_id else Group.default()
        if self.product_id and self.product.group_id != self.group_id:
            from django.core.exceptions import ValidationError

            raise ValidationError("Product belongs to another group.")
        if self.quantity < 0:
            raise ValueError("Damage quantity cannot be negative.")
        price = self.unit_price_snapshot
        if self.product_id:
            product = self.product
            if self._state.adding:
                self.product_id_snapshot = product.pk
                self.product_name_snapshot = product.name
                self.category_snapshot = product.category.name
                self.ctn_size_snapshot = product.ctn_size
            price = product.dealer_price
        if self.related_transaction_id and self.product_id_snapshot is not None:
            item = self.related_transaction.items.filter(
                product_id_snapshot=self.product_id_snapshot
            ).only("sale_price_snapshot").first()
            if item:
                price = item.sale_price_snapshot
        self.unit_price_snapshot = price
        self.value = self.quantity * price
        return super().save(*args, **kwargs)


class StockTransaction(models.Model):
    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="stock_transactions")
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
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name="stock_transactions")
    product_id_snapshot = models.BigIntegerField(null=True, blank=True, editable=False)
    product_name_snapshot = models.CharField(max_length=160, blank=True)
    category_snapshot = models.CharField(max_length=20, blank=True)
    ctn_size_snapshot = models.PositiveIntegerField(default=1)
    dealer = models.ForeignKey(Dealer, on_delete=models.PROTECT, null=True, blank=True, related_name="stock_transactions")
    date = models.DateField()
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.group_id:
            self.group = self.product.group if self.product_id else Group.default()
        if self.product_id and self.product.group_id != self.group_id:
            from django.core.exceptions import ValidationError

            raise ValidationError("Product belongs to another group.")
        if self._state.adding and self.product_id:
            product = self.product
            self.product_id_snapshot = product.pk
            self.product_name_snapshot = product.name
            self.category_snapshot = product.category.name
            self.ctn_size_snapshot = product.ctn_size
        return super().save(*args, **kwargs)

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
