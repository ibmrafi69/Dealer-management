from django.contrib import admin

from .models import GodownStockReceipt


@admin.register(GodownStockReceipt)
class GodownStockReceiptAdmin(admin.ModelAdmin):
    list_display = ("received_at", "product", "received_ctn", "received_pcs", "total_pieces", "reference")
    list_filter = ("received_at", "product__category")
    search_fields = ("product__name", "reference", "notes")
