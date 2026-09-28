from django.contrib import admin
from .models import Product, ProductPriceHistory


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
	list_display = ("name", "category", "ctn_size", "dealer_price", "trade_price", "selling_price", "active")
	list_filter = ("active", "category")
	search_fields = ("name", "category")


@admin.register(ProductPriceHistory)
class ProductPriceHistoryAdmin(admin.ModelAdmin):
	list_display = ("product", "price_type", "old_price", "new_price", "effective_at")
	list_filter = ("price_type", "effective_at")
	search_fields = ("product__name",)
