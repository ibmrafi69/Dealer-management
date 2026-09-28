from django.contrib import admin

from .models import Damage, StockTransaction


@admin.register(Damage)
class DamageAdmin(admin.ModelAdmin):
    list_display = ("date", "product", "quantity", "value", "reason")
    list_filter = ("date",)
    search_fields = ("product__name", "reason")


@admin.register(StockTransaction)
class StockTransactionAdmin(admin.ModelAdmin):
    list_display = ("date", "product", "transaction_type", "quantity", "reference")
    list_filter = ("transaction_type", "date")
    search_fields = ("product__name", "reference")