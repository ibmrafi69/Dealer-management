"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path
from django.urls import include
from django.conf import settings
from django.conf.urls.static import static

from products import views
from sales import views as sales_views
from dealers import views as group_views

urlpatterns = [
    path("", group_views.group_select, name="home"),
    path("groups/", group_views.group_select, name="group-select"),
    path("groups/<int:pk>/open/", group_views.open_group, name="group-open"),
    path("groups/switch/", group_views.switch_group, name="group-switch"),
    path("groups/create/", group_views.create_group, name="group-create"),
    path("groups/<int:pk>/delete/", group_views.delete_group, name="group-delete"),
    path("logout/", group_views.logout_view, name="logout"),
    path("landing/", views.home, name="landing"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("credit/", group_views.dealer_list, name="dealer-list"),
    path("credit/dealers/new/", group_views.dealer_create, name="dealer-create"),
    path("credit/dealers/<int:pk>/", group_views.dealer_detail, name="dealer-detail"),
    path("credit/dealers/<int:pk>/edit/", group_views.dealer_edit, name="dealer-edit"),
    path("credit/dealers/<int:pk>/payment/", group_views.dealer_payment, name="dealer-payment"),
    path("credit/dealers/<int:pk>/credit/", group_views.dealer_credit, name="dealer-credit"),
    path("credit/dealers/<int:pk>/statement/", group_views.dealer_statement, name="dealer-statement"),
    path("credit/dealers/<int:pk>/delete/", group_views.dealer_delete, name="dealer-delete"),
    path("product-setup/", views.product_setup, name="product-setup"),
    path("daily-sales/", sales_views.sales_entry, name="daily-sales-page"),
    path("daily-sales/pending/", sales_views.pending_sales, name="pending-sales"),
    path("daily-summary/", sales_views.daily_summary, name="daily-summary-page"),
    path("products/", include("products.urls")),
    path("sales/", include("sales.urls")),
    path("reports/", include("reports.urls")),
    path("godown-stock/", include("godown_stock.urls")),
    path("admin/", admin.site.urls),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
