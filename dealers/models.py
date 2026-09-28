from django.db import models


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

    route_name = models.CharField(max_length=160, unique=True)
    weekday = models.CharField(max_length=10, choices=WEEKDAY_CHOICES)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def clean(self):
        self.route_name = self.route_name.strip()
        if Route.objects.filter(route_name__iexact=self.route_name).exclude(pk=self.pk).exists():
            from django.core.exceptions import ValidationError

            raise ValidationError({"route_name": "A route with this name already exists."})

    def __str__(self):
        return self.route_name


class Dealer(models.Model):
    name = models.CharField(max_length=160)
    code = models.CharField(max_length=40, unique=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"
