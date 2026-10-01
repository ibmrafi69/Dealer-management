import re

from django.db import models
from django.core.exceptions import ValidationError


class Group(models.Model):
    name = models.CharField(max_length=160, unique=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]

    def clean(self):
        from django.core.exceptions import ValidationError

        self.name = self.name.strip()
        if not self.name:
            raise ValidationError({"name": "Group name is required."})
        if Group.objects.filter(name__iexact=self.name).exclude(pk=self.pk).exists():
            raise ValidationError({"name": "A group with this name already exists."})

    def __str__(self):
        return self.name

    @property
    def is_empty(self):
        return not any(
            relation.exists()
            for relation in (
                self.products,
                self.price_history,
                self.routes,
                self.dealers,
                self.sales_transactions,
                self.sales_items,
                self.stock_receipts,
                self.damages,
                self.stock_transactions,
            )
        )

    def delete(self, *args, **kwargs):
        from django.core.exceptions import ValidationError

        if not self.is_empty:
            raise ValidationError("Groups containing business data cannot be deleted.")
        return super().delete(*args, **kwargs)

    @classmethod
    def default(cls):
        return cls.objects.filter(active=True).order_by("id").first()


class Route(models.Model):
    SATURDAY = "Saturday"
    SUNDAY = "Sunday"
    MONDAY = "Monday"
    TUESDAY = "Tuesday"
    WEDNESDAY = "Wednesday"
    THURSDAY = "Thursday"
    WEEKDAY_CHOICES = (
        (SATURDAY, "Saturday"),
        (SUNDAY, "Sunday"),
        (MONDAY, "Monday"),
        (TUESDAY, "Tuesday"),
        (WEDNESDAY, "Wednesday"),
        (THURSDAY, "Thursday"),
    )
    WEEKDAY_ORDER = [choice[0] for choice in WEEKDAY_CHOICES]
    DEFAULT_ROUTE_SCHEDULE = (
        (SATURDAY, "Doulkhar"),
        (SUNDAY, "Dhalua"),
        (MONDAY, "Boxganj"),
        (TUESDAY, "Bangodda"),
        (WEDNESDAY, "Nangalkot"),
        (THURSDAY, "Bholaine"),
    )
    DEFAULT_ROUTE_BY_WEEKDAY = dict(DEFAULT_ROUTE_SCHEDULE)

    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="routes")
    route_name = models.CharField(max_length=160)
    weekday = models.CharField(max_length=10, choices=WEEKDAY_CHOICES)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["group", "route_name"], name="unique_group_route_name")]

    def clean(self):
        if not self.group_id:
            self.group = Group.default()
        self.route_name = self.route_name.strip()
        if Route.objects.filter(group=self.group, route_name__iexact=self.route_name).exclude(pk=self.pk).exists():
            from django.core.exceptions import ValidationError

            raise ValidationError({"route_name": "A route with this name already exists."})

    def __str__(self):
        return self.route_name

    def save(self, *args, **kwargs):
        if not self.group_id:
            self.group = Group.default()
        self.full_clean()
        return super().save(*args, **kwargs)


class Dealer(models.Model):
    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="dealers")
    route = models.ForeignKey("Route", on_delete=models.PROTECT, null=True, blank=True, related_name="dealers")
    name = models.CharField(max_length=160)
    code = models.CharField(max_length=40)
    address = models.TextField(blank=True)
    location = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    contact_person = models.CharField(max_length=120, blank=True)
    opening_due = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    memo = models.TextField(blank=True)
    memo_image = models.FileField(upload_to="dealer_memos/", blank=True, null=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["group", "code"], name="unique_group_dealer_code")]

    def clean(self):
        if self.route_id and self.group_id and self.route.group_id != self.group_id:
            raise ValidationError({"route": "Route belongs to another group."})

    def __str__(self):
        return f"{self.name} ({self.code})"

    def save(self, *args, **kwargs):
        if not self.group_id:
            self.group = Group.default()
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def current_due(self):
        from .credit import dealer_due

        return dealer_due(self)


def dealer_code_prefix(group):
    words = re.findall(r"[A-Za-z0-9]+", group.name or "GROUP")
    if len(words) >= 3:
        return "".join(word[0] for word in words[:3]).upper()
    if len(words) == 2:
        return f"{words[0][:2]}{words[1][0]}".upper()
    return (words[0][:3] or "GRP").upper()


def next_dealer_code(group):
    prefix = dealer_code_prefix(group)
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$", re.IGNORECASE)
    sequence = max(
        (int(match.group(1)) for code in Dealer.objects.filter(group=group).values_list("code", flat=True) if (match := pattern.match(code or ""))),
        default=0,
    )
    return f"{prefix}-{sequence + 1:04d}"


class DealerPayment(models.Model):
    CASH = "CASH"
    BANK = "BANK"
    MOBILE = "MOBILE"
    OTHER = "OTHER"
    PAYMENT_METHODS = ((CASH, "Cash"), (BANK, "Bank"), (MOBILE, "Mobile Banking"), (OTHER, "Other"))

    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="dealer_payments")
    dealer = models.ForeignKey(Dealer, on_delete=models.PROTECT, related_name="payments")
    payment_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    method = models.CharField(max_length=12, choices=PAYMENT_METHODS, default=CASH)
    reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["payment_date", "created_at", "id"]

    def clean(self):
        if self.dealer_id and self.group_id and self.dealer.group_id != self.group_id:
            raise ValidationError({"dealer": "Dealer belongs to another group."})
        if self.amount is not None and self.amount <= 0:
            raise ValidationError({"amount": "Payment amount must be greater than zero."})
        if self._state.adding and self.dealer_id and self.amount and self.amount > self.dealer.current_due:
            raise ValidationError({"amount": "Payment cannot exceed the dealer's current due."})

    def save(self, *args, **kwargs):
        if not self.group_id and self.dealer_id:
            self.group = self.dealer.group
        self.full_clean()
        return super().save(*args, **kwargs)


class DealerCredit(models.Model):
    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="dealer_credits")
    dealer = models.ForeignKey(Dealer, on_delete=models.PROTECT, related_name="manual_credits")
    credit_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["credit_date", "created_at", "id"]

    def clean(self):
        if self.dealer_id and self.group_id and self.dealer.group_id != self.group_id:
            raise ValidationError({"dealer": "Dealer belongs to another group."})
        if self.amount is not None and self.amount <= 0:
            raise ValidationError({"amount": "Credit amount must be greater than zero."})

    def save(self, *args, **kwargs):
        if not self.group_id and self.dealer_id:
            self.group = self.dealer.group
        self.full_clean()
        return super().save(*args, **kwargs)
