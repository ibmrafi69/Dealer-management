from django.contrib import admin
from .models import Dealer, DealerCredit, DealerPayment, Group, Route


@admin.register(Dealer)
class DealerAdmin(admin.ModelAdmin):
    list_display = ("name", "group", "route", "phone", "opening_due", "active")
    list_filter = ("group", "route", "active")
    search_fields = ("name", "code", "phone", "location")


@admin.register(DealerPayment)
class DealerPaymentAdmin(admin.ModelAdmin):
    list_display = ("dealer", "group", "payment_date", "amount", "method", "reference")
    list_filter = ("group", "method", "payment_date")
    search_fields = ("dealer__name", "reference")


@admin.register(DealerCredit)
class DealerCreditAdmin(admin.ModelAdmin):
    list_display = ("dealer", "group", "credit_date", "amount", "reference")
    list_filter = ("group", "credit_date")
    search_fields = ("dealer__name", "reference", "notes")


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name", "active", "created_at")
    list_filter = ("active",)
    search_fields = ("name",)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ("route_name", "weekday", "active", "created_at")
    list_filter = ("weekday", "active")
    search_fields = ("route_name",)
