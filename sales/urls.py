from django.urls import path

from . import views

urlpatterns = [
    path("", views.sales_entry, name="sales-entry"),
    path("invoice-preview/", views.invoice_preview, name="invoice-preview"),
    path("products/<int:product_id>/history/", views.product_history, name="product-history"),
    path("transactions/<int:pk>/", views.sales_invoice_detail, name="sales-invoice-detail"),
    path("transactions/<int:pk>/edit/", views.sales_edit, name="sales-edit"),
    path("summary/", views.daily_summary, name="daily-summary"),
    path("summary/<str:report_date>/", views.daily_summary, name="daily-summary-date"),
]
