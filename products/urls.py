from django.urls import path

from . import views

urlpatterns = [
	path("", views.product_setup, name="product-list"),
	path("setup/", views.product_setup, name="product-setup"),
	path("setup/<int:pk>/edit/", views.product_edit, name="product-edit"),
]