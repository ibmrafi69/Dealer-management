from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase

from dealers.models import Dealer
from sales.models import SalesItem, SalesTransaction

from .models import Product


class ExcelProductImportTests(TestCase):
    def test_workspace_pages_share_the_persistent_sidebar_toggle(self):
        for path in ("/dashboard/", "/product-setup/", "/daily-sales/", "/daily-summary/", "/reports/monthly/"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertContains(response, 'id="app-sidebar"')
            self.assertContains(response, 'class="sidebar-toggle"')
            self.assertContains(response, 'src="/static/js/sidebar.js"')

        sidebar_script = (Path(settings.BASE_DIR) / "static" / "js" / "sidebar.js").read_text(encoding="utf-8")
        self.assertIn("localStorage", sidebar_script)

    def test_imports_new_zealand_dairy_product_master(self):
        call_command("import_excel_products")
        product = Product.objects.get(name="Diploma 1kg")
        self.assertEqual(Product.objects.count(), 81)
        self.assertEqual(product.category, "Milk")
        self.assertEqual(product.ctn_size, 12)
        self.assertEqual(product.dealer_price, Decimal("871.17"))
        self.assertEqual(product.trade_price, Decimal("893"))
        self.assertEqual(product.selling_price, Decimal("893"))

    def test_product_setup_add_edit_price_history_and_deactivate(self):
        payload = {
            "name": "UI Workflow Product",
            "category": "Milk",
            "ctn_size": "12",
            "dealer_price": "800",
            "trade_price": "850",
            "selling_price": "893",
            "foc": "0",
            "reference_dealer_price": "9000",
            "markup_price": "9225",
        }
        response = self.client.post("/product-setup/", payload)
        self.assertEqual(response.status_code, 302, response.content.decode())
        product = Product.objects.get(name="UI Workflow Product")
        response = self.client.post(f"/products/setup/{product.id}/edit/", {**payload, "selling_price": "900"})
        self.assertEqual(response.status_code, 302)
        product.refresh_from_db()
        self.assertEqual(product.selling_price, Decimal("900.00"))
        self.assertEqual(product.price_history.get().new_price, Decimal("900.00"))

        response = self.client.post("/product-setup/", {"action": "toggle", "product_id": product.id})
        self.assertEqual(response.status_code, 302)
        product.refresh_from_db()
        self.assertFalse(product.active)
        self.assertNotIn(b"UI Workflow Product", self.client.get("/daily-sales/").content)

    def test_search_category_status_and_pagination_filters(self):
        call_command("import_excel_products")
        response = self.client.get("/product-setup/?q=diploma&category=Milk&status=active")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Diploma 1kg")
        self.assertNotContains(response, "Doodles 33gm")
        response = self.client.get("/product-setup/?q=milk")
        self.assertEqual(response.status_code, 200)
        response = self.client.get("/product-setup/?status=inactive")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["status_filter"], "inactive")
        response = self.client.get("/product-setup/?q=diploma&page=2")
        self.assertEqual(response.status_code, 200)
        self.assertIn("q=diploma", response.context["filter_query"])

    def test_unused_product_can_be_deleted(self):
        product = Product.objects.create(name="Unused Product", selling_price=10)
        response = self.client.post("/product-setup/", {"action": "delete", "product_id": product.id})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Product.objects.filter(pk=product.id).exists())

    def test_referenced_product_is_deactivated_and_can_reactivate(self):
        dealer = Dealer.objects.create(name="History Dealer", code="HIST")
        product = Product.objects.create(name="Referenced Product", selling_price=10)
        sale = SalesTransaction.objects.create(dealer=dealer, date="2026-09-26", invoice_number="HIST-1")
        SalesItem.objects.create(transaction=sale, product=product, order_quantity=1)
        response = self.client.post("/product-setup/", {"action": "delete", "product_id": product.id})
        self.assertEqual(response.status_code, 302)
        product.refresh_from_db()
        self.assertFalse(product.active)
        self.assertNotContains(self.client.get("/daily-sales/"), "Referenced Product")
        self.assertContains(self.client.get("/daily-summary/?date=2026-09-26"), "Referenced Product")
        response = self.client.post("/product-setup/", {"action": "toggle", "product_id": product.id})
        self.assertEqual(response.status_code, 302)
        product.refresh_from_db()
        self.assertTrue(product.active)

    def test_price_change_preserves_historical_sales_snapshot(self):
        dealer = Dealer.objects.create(name="Snapshot Dealer", code="SNAP")
        product = Product.objects.create(name="Snapshot Product", selling_price=893, trade_price=893)
        old_sale = SalesTransaction.objects.create(dealer=dealer, date="2026-09-26", invoice_number="OLD-1")
        old_item = SalesItem.objects.create(transaction=old_sale, product=product, order_quantity=1)

        product.selling_price = Decimal("900")
        product.save()

        new_sale = SalesTransaction.objects.create(dealer=dealer, date="2026-09-27", invoice_number="NEW-1")
        new_item = SalesItem.objects.create(transaction=new_sale, product=product, order_quantity=1)

        old_item.refresh_from_db()
        self.assertEqual(old_item.sale_price_snapshot, Decimal("893.00"))
        self.assertEqual(old_item.unit_price, Decimal("893.00"))
        self.assertEqual(new_item.sale_price_snapshot, Decimal("900.00"))
        self.assertEqual(new_item.unit_price, Decimal("900.00"))
        self.assertEqual(product.price_history.count(), 1)
        self.assertEqual(product.price_history.first().price_type, "SALE_PRICE")
from django.test import TestCase

# Create your tests here.
