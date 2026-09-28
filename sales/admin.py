from django.contrib import admin

from .models import PaymentReconciliation, SalesItem, SalesTransaction


class SalesItemInline(admin.TabularInline):
    model = SalesItem
    extra = 0
    readonly_fields = ("sale_quantity", "unit_price", "sale_value")


@admin.register(SalesTransaction)
class SalesTransactionAdmin(admin.ModelAdmin):
    list_display = ("invoice_number", "status", "route", "dealer", "date", "updated_at")
    list_filter = ("status", "date", "route", "dealer")
    search_fields = ("invoice_number", "route__route_name", "dealer__name")
    inlines = (SalesItemInline,)


@admin.register(PaymentReconciliation)
class PaymentReconciliationAdmin(admin.ModelAdmin):
    list_display = ("transaction", "cash", "credit", "shortage")