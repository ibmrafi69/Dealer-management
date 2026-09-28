from django.contrib import admin
from .models import Route


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ("route_name", "weekday", "active", "created_at")
    list_filter = ("weekday", "active")
    search_fields = ("route_name",)
