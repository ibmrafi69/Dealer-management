from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from dealers.models import Dealer
from dealers.models import Group
from dealers.models import Route
from products.models import Product


CURRENCY_DENOMINATIONS = (1000, 500, 200, 100, 50, 20, 10, 5, 1)


class SalesTransaction(models.Model):
    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="sales_transactions")
    dealer = models.ForeignKey(Dealer, on_delete=models.PROTECT, null=True, blank=True, related_name="sales_transactions")
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        FINALIZED = "FINALIZED", "Finalized"

    route = models.ForeignKey(Route, on_delete=models.PROTECT, null=True, blank=True, related_name="sales_transactions")
    route_day = models.CharField(max_length=10, blank=True)
    date = models.DateField()
    invoice_number = models.CharField(max_length=60)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.FINALIZED, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["dealer", "date", "invoice_number"], name="unique_dealer_invoice_date"),
            models.UniqueConstraint(fields=["route", "date", "invoice_number"], name="unique_route_invoice_date"),
            models.UniqueConstraint(fields=["invoice_number"], name="unique_invoice_number"),
        ]

    @classmethod
    def next_invoice_number(cls, transaction_date):
        prefix = f"AE-{transaction_date:%Y%m%d}-"
        used_numbers = cls.objects.filter(invoice_number__startswith=prefix).values_list("invoice_number", flat=True)
        sequence = max(
            (int(invoice_number[len(prefix):]) for invoice_number in used_numbers if invoice_number[len(prefix):].isdigit()),
            default=0,
        )
        return f"{prefix}{sequence + 1:04d}"

    def __str__(self):
        location = self.route.route_name if self.route_id else self.dealer.name
        return f"{self.invoice_number} - {location}"

    def clean(self):
        errors = {}
        if self.route_id and self.group_id and self.route.group_id != self.group_id:
            errors["route"] = "Route belongs to another group."
        if self.dealer_id and self.group_id and self.dealer.group_id != self.group_id:
            errors["dealer"] = "Dealer belongs to another group."
        if errors:
            from django.core.exceptions import ValidationError

            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.group_id:
            self.group = Group.default()
        if self._state.adding and not self.invoice_number:
            self.invoice_number = self.next_invoice_number(self.date)
        if self._state.adding and self.route_id and not self.route_day:
            self.route_day = self.route.weekday
        if self.route_id and self.route.group_id != self.group_id:
            from django.core.exceptions import ValidationError

            raise ValidationError("Route belongs to another group.")
        if self.dealer_id and self.dealer.group_id != self.group_id:
            from django.core.exceptions import ValidationError

            raise ValidationError("Dealer belongs to another group.")
        super().save(*args, **kwargs)

    @property
    def route_display(self):
        return self.route.route_name if self.route_id else self.dealer.name

    def _item_total(self, field_name):
        """Return a saved invoice-line total without recalculating its prices."""
        return sum((getattr(item, field_name) for item in self.items.all()), Decimal("0"))

    def _item_piece_total(self, field_name):
        """Return saved Daily Sales quantities, which are already in pieces."""
        return sum(
            (getattr(item, field_name) for item in self.items.all()),
            Decimal("0"),
        )

    @property
    def sent_quantity_total(self):
        return self._item_total("order_quantity")

    @property
    def sent_pieces_total(self):
        return self._item_piece_total("order_quantity")

    @property
    def return_quantity_total(self):
        return self._item_total("return_quantity")

    @property
    def return_pieces_total(self):
        return self._item_piece_total("return_quantity")

    @property
    def damage_quantity_total(self):
        return self._item_total("damage_quantity")

    @property
    def damage_pieces_total(self):
        return self._item_piece_total("damage_quantity")

    @property
    def sale_quantity_total(self):
        return self._item_total("sale_quantity")

    @property
    def sale_pieces_total(self):
        return self._item_piece_total("sale_quantity")

    @property
    def order_total(self):
        return sum((item.order_value for item in self.items.all()), Decimal("0"))

    @property
    def return_total(self):
        return sum((item.return_value for item in self.items.all()), Decimal("0"))

    @property
    def sale_total(self):
        return sum((item.sale_value for item in self.items.all()), Decimal("0"))

    @property
    def discount_total(self):
        return sum((item.discount for item in self.items.all()), Decimal("0"))

    @property
    def reconciliation_discount(self):
        return getattr(getattr(self, "reconciliation", None), "discount", Decimal("0"))

    @property
    def total_discount(self):
        return self.discount_total + self.reconciliation_discount

    @property
    def foc_total(self):
        return sum((item.foc_quantity for item in self.items.all()), Decimal("0"))

    @property
    def free_product_total(self):
        return sum((item.free_product_value for item in self.items.all()), Decimal("0"))

    @property
    def damage_total(self):
        item_damages = [item for item in self.items.all() if item.damage_quantity]
        item_damage_total = sum((item.damage_value for item in item_damages), Decimal("0"))
        item_damage_product_ids = {item.product_id_snapshot if item.product_id_snapshot is not None else item.product_id for item in item_damages}
        unitemized_damage_total = sum(
            (damage.value for damage in self.damages.all() if (damage.product_id_snapshot if damage.product_id_snapshot is not None else damage.product_id) not in item_damage_product_ids),
            Decimal("0"),
        )
        return item_damage_total + unitemized_damage_total

    @property
    def unitemized_damage_total(self):
        item_damage_product_ids = {item.product_id_snapshot if item.product_id_snapshot is not None else item.product_id for item in self.items.all() if item.damage_quantity}
        return sum(
            (damage.value for damage in self.damages.all() if (damage.product_id_snapshot if damage.product_id_snapshot is not None else damage.product_id) not in item_damage_product_ids),
            Decimal("0"),
        )

    @property
    def net_sale(self):
        return self.grand_total_sale - self.total_discount - self.free_product_total

    @property
    def grand_total_sale(self):
        # SalesItem.sale_quantity already excludes its recorded damage. Only
        # standalone damage records still need to reduce the transaction total.
        return self.sale_total - self.unitemized_damage_total


class CurrencyCount(models.Model):
    """The physical cash count saved with one daily-sales invoice."""

    transaction = models.OneToOneField(SalesTransaction, on_delete=models.CASCADE, related_name="currency_count")
    quantity_1000 = models.PositiveIntegerField(default=0)
    quantity_500 = models.PositiveIntegerField(default=0)
    quantity_200 = models.PositiveIntegerField(default=0)
    quantity_100 = models.PositiveIntegerField(default=0)
    quantity_50 = models.PositiveIntegerField(default=0)
    quantity_20 = models.PositiveIntegerField(default=0)
    quantity_10 = models.PositiveIntegerField(default=0)
    quantity_5 = models.PositiveIntegerField(default=0)
    quantity_1 = models.PositiveIntegerField(default=0)
    total_cash = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)

    @staticmethod
    def quantity_field(denomination):
        return f"quantity_{denomination}"

    def quantity_for(self, denomination):
        return getattr(self, self.quantity_field(denomination))

    @property
    def rows(self):
        return [
            (denomination, self.quantity_for(denomination), Decimal(denomination) * self.quantity_for(denomination))
            for denomination in CURRENCY_DENOMINATIONS
        ]

    def save(self, *args, **kwargs):
        self.total_cash = sum(
            (Decimal(denomination) * self.quantity_for(denomination) for denomination in CURRENCY_DENOMINATIONS),
            Decimal("0"),
        ).quantize(Decimal("0.01"))
        return super().save(*args, **kwargs)
class SalesItem(models.Model):
    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="sales_items")
    transaction = models.ForeignKey(SalesTransaction, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name="sales_items")
    product_id_snapshot = models.BigIntegerField(null=True, blank=True, editable=False)
    order_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    return_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sale_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    foc_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    free_product_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    damage_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    damage_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    product_name_snapshot = models.CharField(max_length=160, blank=True)
    category_snapshot = models.CharField(max_length=80, blank=True)
    ctn_size_snapshot = models.PositiveIntegerField(default=1)
    dealer_price_snapshot = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    trade_price_snapshot = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sale_price_snapshot = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    foc_snapshot = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    sale_value = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["transaction", "product"], name="unique_product_per_transaction")]

    def clean(self):
        errors = {}
        if not self.group_id and self.transaction_id:
            self.group = self.transaction.group
        if self.product_id and self.group_id and self.product.group_id != self.group_id:
            errors["product"] = "Product belongs to another group."
        for field in ("order_quantity", "return_quantity", "foc_quantity", "free_product_quantity", "damage_quantity", "discount", "dealer_price_snapshot", "trade_price_snapshot", "foc_snapshot", "sale_price_snapshot"):
            if getattr(self, field) < 0:
                errors[field] = "This value cannot be negative."
        if self.return_quantity + self.damage_quantity > self.order_quantity:
            errors["return_quantity"] = "Return and damage quantities together cannot exceed order quantity."
            errors["damage_quantity"] = "Return and damage quantities together cannot exceed order quantity."
        if errors:
            raise ValidationError(errors)

    @property
    def order_value(self):
        return self.order_quantity * self.unit_price

    @property
    def return_value(self):
        return self.return_quantity * self.unit_price

    @property
    def foc_value(self):
        return self.foc_quantity * self.unit_price

    @property
    def free_product_value(self):
        return self.free_product_quantity * self.unit_price

    def save(self, *args, **kwargs):
        if not self.group_id and self.transaction_id:
            self.group = self.transaction.group
        self.order_quantity = Decimal(str(self.order_quantity or 0))
        self.return_quantity = Decimal(str(self.return_quantity or 0))
        self.foc_quantity = Decimal(str(self.foc_quantity or 0))
        self.free_product_quantity = Decimal(str(self.free_product_quantity or 0))
        self.damage_quantity = Decimal(str(self.damage_quantity or 0))
        self.discount = Decimal(str(self.discount or 0))
        self.dealer_price_snapshot = Decimal(str(self.dealer_price_snapshot or 0))
        self.trade_price_snapshot = Decimal(str(self.trade_price_snapshot or 0))
        self.foc_snapshot = Decimal(str(self.foc_snapshot or 0))
        self.sale_price_snapshot = Decimal(str(self.sale_price_snapshot or 0))
        if self._state.adding and self.product_id:
            product = self.product
            self.product_id_snapshot = product.pk
            self.product_name_snapshot = product.name
            self.category_snapshot = product.category.name
            self.ctn_size_snapshot = product.ctn_size
            self.dealer_price_snapshot = product.dealer_price
            self.trade_price_snapshot = product.trade_price
            self.sale_price_snapshot = product.effective_sale_price
            self.foc_snapshot = product.foc
        self.unit_price = self.sale_price_snapshot
        self.sale_quantity = self.order_quantity - self.return_quantity - self.damage_quantity
        self.sale_value = (self.sale_quantity * self.unit_price).quantize(Decimal("0.01"))
        self.damage_value = (self.damage_quantity * self.unit_price).quantize(Decimal("0.01"))
        self.full_clean()
        return super().save(*args, **kwargs)


class PaymentReconciliation(models.Model):
    transaction = models.OneToOneField(SalesTransaction, on_delete=models.CASCADE, related_name="reconciliation")
    cash = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    expenses = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    others = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    shortage = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)

    def save(self, *args, **kwargs):
        for field in ("cash", "expenses", "credit", "discount", "others"):
            setattr(self, field, Decimal(str(getattr(self, field) or 0)))
        self.shortage = (
            self.transaction.grand_total_sale
            - self.cash
            - self.expenses
            - self.credit
            - self.discount
            - self.others
        ).quantize(Decimal("0.01"))
        return super().save(*args, **kwargs)

    @property
    def net_sale(self):
        return self.transaction.net_sale
