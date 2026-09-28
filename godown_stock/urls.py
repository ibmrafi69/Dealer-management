from django.urls import path

from . import views


urlpatterns = [
    path("", views.godown_stock, name="godown-stock"),
    path("add/", views.add_stock, name="godown-add-stock"),
    path("history/", views.stock_history_view, name="godown-stock-history"),
    path("history/<int:product_id>/", views.stock_history_view, name="godown-stock-history-product"),
]
