from django.urls import path

from . import views

urlpatterns = [
    path("", views.monthly_report, name="reports-home"),
    path("daily/export/", views.export_daily, name="daily-export"),
    path("monthly/", views.monthly_report, name="monthly-report"),
    path("monthly/export/", views.export_monthly, name="monthly-export"),
    path("monthly/export/pdf/", views.export_monthly_pdf, name="monthly-pdf-export"),
]
