from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase

from dealers.models import Group, Route
from godown_stock.models import GodownStockReceipt
from godown_stock.services import stock_rows
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
        self.assertEqual(product.group.name, "New Zealand Dairy")
        self.assertEqual(Product.objects.filter(group=product.group).count(), 81)
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

    def test_referenced_product_is_deleted_with_historical_snapshots_intact(self):
        from godown_stock.models import GodownStockReceipt
        from inventory.models import Damage, StockTransaction
        dealer = Dealer.objects.create(name="History Dealer", code="HIST")
        product = Product.objects.create(name="Referenced Product", category=Product.MILK, ctn_size=12, dealer_price=8, trade_price=10, selling_price=10)
        product.selling_price = Decimal("12")
        product.save()
        price_history = product.price_history.get()
        sale = SalesTransaction.objects.create(dealer=dealer, date="2026-09-26", invoice_number="HIST-1")
        item = SalesItem.objects.create(transaction=sale, product=product, order_quantity=1)
        damage = Damage.objects.create(date=sale.date, product=product, quantity=1, related_transaction=sale)
        stock_transaction = StockTransaction.objects.create(product=product, dealer=dealer, date=sale.date, transaction_type=StockTransaction.SALE, quantity=-1, reference=sale.invoice_number)
        receipt = GodownStockReceipt.objects.create(product=product, received_ctn=1)
        old_product_id = product.id
        response = self.client.post("/product-setup/", {"action": "delete", "product_id": old_product_id})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Product.objects.filter(pk=old_product_id).exists())
        item.refresh_from_db()
        self.assertIsNone(item.product)
        self.assertEqual(item.product_id_snapshot, old_product_id)
        self.assertEqual(item.product_name_snapshot, "Referenced Product")
        damage.refresh_from_db()
        self.assertIsNone(damage.product)
        self.assertEqual(damage.product_id_snapshot, old_product_id)
        stock_transaction.refresh_from_db()
        self.assertIsNone(stock_transaction.product)
        self.assertEqual(stock_transaction.product_id_snapshot, old_product_id)
        receipt.refresh_from_db()
        self.assertIsNone(receipt.product)
        self.assertEqual(receipt.product_id_snapshot, old_product_id)
        price_history.refresh_from_db()
        self.assertIsNone(price_history.product)
        self.assertEqual(price_history.product_id_snapshot, old_product_id)
        self.assertEqual(price_history.product_name_snapshot, "Referenced Product")
        self.assertNotContains(self.client.get("/daily-sales/"), "Referenced Product")
        self.assertContains(self.client.get("/daily-summary/?date=2026-09-26"), "Referenced Product")
        self.assertNotContains(self.client.get("/godown-stock/"), "Referenced Product")
        replacement = Product.objects.create(name="Referenced Product", category=Product.MILK, ctn_size=12, selling_price=10)
        self.assertNotEqual(replacement.id, old_product_id)
        self.assertContains(self.client.get("/daily-sales/"), "Referenced Product")

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



class BDFoodsProductTests(TestCase):
    def setUp(self):
        self.group = Group.objects.get(name="BD Foods")

    def test_reference_products_are_seeded_with_configured_units_and_prices(self):
        self.assertEqual(self.group.products.count(), 19)
        product = self.group.products.get(name="Potato crackers 15gm")
        self.assertEqual((product.ctn_size, product.unit, product.dealer_price, product.selling_price), (80, "single", Decimal("600.00"), Decimal("630.00")))
        chutney = self.group.products.get(name="BD Tamarind Chutney")
        self.assertEqual((chutney.ctn_size, chutney.unit, chutney.dealer_price, chutney.selling_price), (432, "dozen", Decimal("1584.00"), Decimal("47.00")))
        missing = self.group.products.get(name="Happy Cow 200/500 Ndls")
        self.assertEqual((missing.ctn_size, missing.unit, missing.dealer_price, missing.selling_price), (1, "unit", Decimal("0.00"), Decimal("0.00")))

    def test_reference_calculations_use_saved_sale_and_return_prices(self):
        potato = self.group.products.get(name="Potato crackers 15gm")
        sale = SalesTransaction.objects.create(group=self.group, date="2026-10-01", invoice_number="BD-CALC-1")
        item = SalesItem.objects.create(group=self.group, transaction=sale, product=potato, order_quantity=36)
        self.assertEqual(item.sale_quantity, Decimal("36.00"))
        self.assertEqual(item.sale_value, Decimal("22680.00"))

        chutney = self.group.products.get(name="BD Tamarind Chutney")
        return_sale = SalesTransaction.objects.create(group=self.group, date="2026-10-01", invoice_number="BD-CALC-2")
        returned = SalesItem.objects.create(group=self.group, transaction=return_sale, product=chutney, order_quantity=12, return_quantity=12)
        self.assertEqual(returned.return_value, Decimal("564.00"))
        self.assertEqual(returned.sale_quantity, Decimal("0.00"))

    def test_bd_products_start_with_zero_stock_and_nzd_catalog_is_unchanged(self):
        product = self.group.products.get(name="BD Jhal Chanachur 150 gm")
        self.assertEqual(stock_rows([product])[0]["balance_pieces"], Decimal("0"))
        self.assertTrue(Group.objects.get(name="New Zealand Dairy").active)


class DashboardTests(TestCase):
    def setUp(self):
        self.nzd = Group.objects.get(name="New Zealand Dairy")
        self.bd = Group.objects.get(name="BD Foods")
        self.nzd_route = Route.objects.create(group=self.nzd, route_name="Dashboard NZD", weekday=Route.MONDAY)
        self.bd_route = Route.objects.create(group=self.bd, route_name="Dashboard BD", weekday=Route.MONDAY)
        self.nzd_product = Product.objects.create(group=self.nzd, name="Dashboard NZD Product", category=Product.MILK, selling_price=100)
        self.bd_product = self.bd.products.get(name="Potato crackers 15gm")

    def switch_to(self, group):
        response = self.client.post("/groups/switch/", {"group_id": group.pk, "next": "/dashboard/"})
        self.assertEqual(response.status_code, 302)

    def create_sale(self, group, route, product, invoice, sale_date, status=SalesTransaction.Status.FINALIZED, quantity=1):
        transaction = SalesTransaction.objects.create(group=group, route=route, date=sale_date, invoice_number=invoice, status=status)
        SalesItem.objects.create(group=group, transaction=transaction, product=product, order_quantity=quantity)
        return transaction

    def test_dashboard_is_group_and_month_specific_and_excludes_pending(self):
        self.create_sale(self.nzd, self.nzd_route, self.nzd_product, "NZD-DASH-SEP", "2026-09-15", quantity=3)
        self.create_sale(self.nzd, self.nzd_route, self.nzd_product, "NZD-DASH-PENDING", "2026-09-16", status=SalesTransaction.Status.PENDING, quantity=9)
        bd_sale = self.create_sale(self.bd, self.bd_route, self.bd_product, "BD-DASH-OCT", "2026-10-01", quantity=2)
        second_product = Product.objects.create(group=self.bd, name="Dashboard BD Second", category=Product.MILK, selling_price=5)
        SalesItem.objects.create(group=self.bd, transaction=bd_sale, product=second_product, order_quantity=4)

        self.switch_to(self.nzd)
        september = self.client.get("/dashboard/?year=2026&month=9")
        self.assertEqual(september.context["monthly"]["orders"], 1)
        self.assertEqual(september.context["monthly"]["sales"], Decimal("300.00"))
        self.assertContains(september, "NZD-DASH-SEP")
        self.assertNotContains(september, "BD-DASH-OCT")
        self.assertEqual(len(september.context["sales_trend"]), 30)

        self.switch_to(self.bd)
        october = self.client.get("/dashboard/?year=2026&month=10")
        self.assertEqual(october.context["monthly"]["orders"], 1)
        self.assertEqual(october.context["monthly"]["sales"], Decimal("1280.00"))
        self.assertContains(october, "BD-DASH-OCT")
        self.assertNotContains(october, "NZD-DASH-SEP")
        self.assertEqual(len(october.context["sales_trend"]), 31)
        self.assertEqual(october.context["top_products"][0]["quantity"], Decimal("4.00"))

    def test_dashboard_stock_overview_uses_existing_stock_rows(self):
        GodownStockReceipt.objects.create(group=self.bd, product=self.bd_product, received_ctn=1)
        self.switch_to(self.bd)
        response = self.client.get("/dashboard/?year=2026&month=10")
        self.assertEqual(response.context["active_product_count"], self.bd.products.filter(active=True).count())
        self.assertEqual(response.context["in_stock_count"], 1)
        self.assertEqual(response.context["out_of_stock_count"], self.bd.products.filter(active=True).count() - 1)
from django.test import TestCase

# Create your tests here.
