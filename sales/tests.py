from datetime import date
from decimal import Decimal
import os
from pathlib import Path

from django.db import IntegrityError
from django.test import TestCase

from dealers.credit import dealer_due
from dealers.models import Dealer, Route
from godown_stock.models import GodownStockReceipt
from godown_stock.services import stock_balances
from inventory.models import Damage, StockTransaction
from products.models import Product

from .models import CurrencyCount, PaymentReconciliation, SalesItem, SalesTransaction


class SalesCalculationTests(TestCase):
    def setUp(self):
        self.dealer = Dealer.objects.create(name="Test Dealer", code="TEST", route=Route.objects.get(route_name="Dhalua"))
        self.product = Product.objects.create(name="Milk 1kg", trade_price=Decimal("100"), dealer_price=Decimal("80"))
        GodownStockReceipt.objects.create(product=self.product, received_ctn=1000, reference="SALES-TEST-STOCK")

    def test_transaction_calculations_and_returns(self):
        sale = SalesTransaction.objects.create(dealer=self.dealer, date=date(2026, 9, 26), invoice_number="INV-1")
        item = SalesItem.objects.create(transaction=sale, product=self.product, order_quantity=10, return_quantity=2, foc_quantity=1, discount=5)
        sale.refresh_from_db()
        self.assertEqual(item.sale_quantity, Decimal("8.00"))
        self.assertEqual(item.sale_value, Decimal("800.00"))
        self.assertEqual(sale.net_sale, Decimal("795.00"))

    def test_row_quantity_value_pairs_use_the_saved_sale_price(self):
        self.product.selling_price = Decimal("675")
        self.product.save()
        sale = SalesTransaction.objects.create(dealer=self.dealer, date=date(2026, 9, 26), invoice_number="INV-PAIR")
        item = SalesItem.objects.create(
            transaction=sale,
            product=self.product,
            order_quantity=12,
            return_quantity=2,
            damage_quantity=1,
            free_product_quantity=1,
        )

        self.assertEqual(item.sale_price_snapshot, Decimal("675.00"))
        self.assertEqual(item.return_value, Decimal("1350.00"))
        self.assertEqual(item.sale_quantity, Decimal("9.00"))
        self.assertEqual(item.sale_value, Decimal("6075.00"))
        self.assertEqual(item.damage_value, Decimal("675.00"))
        self.assertEqual(item.free_product_value, Decimal("675.00"))
        self.assertEqual(sale.grand_total_sale, Decimal("6075.00"))

    def test_workbook_style_free_product_and_reconciliation(self):
        self.product.trade_price = Decimal("15.50")
        self.product.selling_price = Decimal("16.13")
        self.product.save()
        sale = SalesTransaction.objects.create(dealer=self.dealer, date=date(2026, 9, 26), invoice_number="INV-3")
        item = SalesItem.objects.create(
            transaction=sale,
            product=self.product,
            order_quantity=720,
            return_quantity=15,
            free_product_quantity=3,
        )
        self.assertEqual(item.sale_quantity, Decimal("705.00"))
        self.assertEqual(item.sale_value, Decimal("11371.65"))
        self.assertEqual(item.order_value, Decimal("11613.60"))
        self.assertEqual(item.return_value, Decimal("241.95"))
        self.assertEqual(item.free_product_value, Decimal("48.39"))

        from inventory.models import Damage

        Damage.objects.create(date=sale.date, product=self.product, quantity=10, related_transaction=sale)
        PaymentReconciliation.objects.create(transaction=sale, cash=10000, credit=500, discount=20)
        sale.refresh_from_db()
        self.assertEqual(sale.damage_total, Decimal("161.30"))
        self.assertEqual(sale.grand_total_sale, Decimal("11210.35"))
        self.assertEqual(sale.net_sale, Decimal("11141.96"))

    def test_expenses_and_shortage_are_reported_separately(self):
        self.product.selling_price = Decimal("100")
        self.product.save()
        sale = SalesTransaction.objects.create(
            dealer=self.dealer,
            date=date(2026, 9, 26),
            invoice_number="INV-EXPENSE-SEPARATION",
            status=SalesTransaction.Status.FINALIZED,
        )
        SalesItem.objects.create(transaction=sale, product=self.product, order_quantity=100)
        reconciliation = PaymentReconciliation.objects.create(transaction=sale, cash=9400, expenses=500)
        self.assertEqual(reconciliation.expenses, Decimal("500.00"))
        self.assertEqual(reconciliation.shortage, Decimal("100.00"))

    def test_return_cannot_exceed_order(self):
        sale = SalesTransaction.objects.create(dealer=self.dealer, date=date(2026, 9, 26), invoice_number="INV-2")
        with self.assertRaises(Exception):
            SalesItem.objects.create(transaction=sale, product=self.product, order_quantity=1, return_quantity=2)

    def test_daily_sales_entry_accepts_multiple_products(self):
        second_product = Product.objects.create(name="Tea", trade_price=50, selling_price=55)
        GodownStockReceipt.objects.create(product=second_product, received_ctn=100, reference="SALES-TEST-TEA-STOCK")
        response = self.client.post(
            "/sales/",
            {
                "date": "2026-09-26",
                "dealer": self.dealer.id,
                "invoice_number": "INV-MULTI",
                "product_id": [self.product.id, second_product.id],
                "order_quantity": ["10", "4"],
                "return_quantity": ["2", "1"],
                "foc_quantity": ["0", "1"],
                "free_product_quantity": ["0", "0"],
                "discount": ["5", "0"],
                "damage_quantity": ["0", "1"],
                "cash": "500",
                "expenses": "0",
                "credit": "0",
                "payment_discount": "0",
                "others": "0",
            },
        )
        self.assertEqual(response.status_code, 302, response.content.decode())
        sale = SalesTransaction.objects.get(date=date(2026, 9, 26), dealer=self.dealer)
        self.assertEqual(sale.items.count(), 2)
        self.assertEqual(sale.items.get(product=self.product).sale_quantity, Decimal("8.00"))
        self.assertEqual(sale.damages.count(), 1)

    def test_daily_sales_defaults_missing_optional_row_values(self):
        second_product = Product.objects.create(name="Tea", trade_price=50, selling_price=55)
        response = self.client.post(
            "/sales/",
            {
                "date": "2026-09-27",
                "route_name": "Dhalua",
                "route_weekday": "Sunday",
                "product_id": [self.product.id, second_product.id],
                "order_quantity": ["1"],
                "return_quantity": ["0"],
                "foc_quantity": ["0"],
                "free_product_quantity": ["0"],
                "damage_quantity": ["0"],
                "discount": ["0"],
            }
        )
        self.assertEqual(response.status_code, 302)
        sale = SalesTransaction.objects.get(date=date(2026, 9, 27))
        self.assertEqual(sale.items.count(), 2)
        self.assertEqual(sale.items.get(product=second_product).order_quantity, Decimal("0"))

    def test_daily_summary_cumulative_totals_cover_all_filtered_dates(self):
        dhalua = Route.objects.get(route_name="Dhalua")
        boxganj = Route.objects.get(route_name="Boxganj")
        first = SalesTransaction.objects.create(route=dhalua, date=date(2026, 9, 27))
        second = SalesTransaction.objects.create(route=boxganj, date=date(2026, 9, 28))
        SalesItem.objects.create(transaction=first, product=self.product, order_quantity=10, return_quantity=1, discount=10)
        SalesItem.objects.create(transaction=second, product=self.product, order_quantity=20, return_quantity=2, discount=20)
        PaymentReconciliation.objects.create(transaction=first, cash=800)
        PaymentReconciliation.objects.create(transaction=second, cash=1500)
        response = self.client.get("/daily-summary/?year=2026&month=9")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["daily_records"].__len__(), 2)
        self.assertEqual(response.context["totals"]["sales"], Decimal("2700"))
        self.assertEqual(response.context["totals"]["returns"], Decimal("300"))
        self.assertEqual(response.context["totals"]["discount"], Decimal("30"))
        self.assertEqual(response.context["totals"]["net"], Decimal("2670"))
        route_response = self.client.get(f"/daily-summary/?year=2026&month=9&route={dhalua.id}")
        self.assertEqual(route_response.context["daily_records"].__len__(), 1)
        self.assertEqual(route_response.context["totals"]["sales"], Decimal("900"))

    def test_daily_summary_shows_stored_total_pieces(self):
        self.product.ctn_size = 12
        self.product.save()
        route = Route.objects.get(route_name="Dhalua")
        sale = SalesTransaction.objects.create(route=route, date=date(2026, 9, 27))
        SalesItem.objects.create(
            transaction=sale,
            product=self.product,
            order_quantity=10,
            return_quantity=2,
        )

        response = self.client.get("/daily-summary/?date=2026-09-27")

        self.assertEqual(response.status_code, 200)
        product_total = response.context["product_details"][0]
        self.assertEqual(product_total["sale"], Decimal("8.00"))
        self.assertEqual(product_total["pieces"], Decimal("8.00"))
        self.assertEqual(product_total["value"], Decimal("800.00"))
        self.assertContains(response, "Sold pieces")
        self.assertContains(response, "Total sale (Tk)")

    def test_invoice_summary_link_opens_read_only_finalized_invoice(self):
        product = Product.objects.create(name="Happy Cow 1kg", trade_price=675, selling_price=675)
        GodownStockReceipt.objects.create(product=product, received_ctn=100, reference="HAPPY-COW-TEST-STOCK")
        morning = self.client.post(
            "/sales/",
            {
                "date": "2026-09-30",
                "route_name": "Nangalkot",
                "route_weekday": "Wednesday",
                "product_id": [product.id],
                "order_quantity": ["12"],
                "return_quantity": ["0"],
                "foc_quantity": ["0"],
                "free_product_quantity": ["0"],
                "damage_quantity": ["0"],
                "discount": ["0"],
            }
        )
        self.assertEqual(morning.status_code, 302)
        sale = SalesTransaction.objects.get(date=date(2026, 9, 30), route__route_name="Nangalkot")
        invoice_number = sale.invoice_number
        summary = self.client.get("/daily-summary/?year=2026&month=9")
        self.assertContains(summary, f'href="/sales/transactions/{sale.id}/"')
        self.assertNotContains(summary, f'/sales/transactions/{sale.id}/edit/')
        invoice_view = self.client.get(f"/sales/transactions/{sale.id}/")
        self.assertEqual(invoice_view.status_code, 200)
        self.assertContains(invoice_view, invoice_number)
        self.assertContains(invoice_view, "Read-only invoice detail")
        self.assertNotContains(invoice_view, 'id="invoice-edit-form"')
        edit = self.client.get(f"/sales/transactions/{sale.id}/edit/")
        self.assertEqual(edit.status_code, 200)
        item = sale.items.get()
        evening = self.client.post(
            f"/sales/transactions/{sale.id}/edit/",
            {
                "notes": "Evening return update",
                f"return_quantity_{item.id}": "2",
                f"damage_quantity_{item.id}": "1",
                f"foc_quantity_{item.id}": "0",
                f"free_product_quantity_{item.id}": "0",
                f"discount_{item.id}": "0",
                f"dealer_price_{item.id}": "658",
                f"trade_price_{item.id}": "675",
                f"foc_price_{item.id}": "0",
                f"sale_price_{item.id}": "680",
                "cash": "6000",
                "expenses": "0",
                "credit": "0",
                "discount": "0",
                "others": "0",
            },
        )
        self.assertEqual(evening.status_code, 302)
        sale.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(SalesTransaction.objects.filter(invoice_number=invoice_number).count(), 1)
        self.assertEqual(sale.invoice_number, invoice_number)
        self.assertEqual(item.order_quantity, Decimal("12.00"))
        self.assertEqual(item.return_quantity, Decimal("2.00"))
        self.assertEqual(item.sale_quantity, Decimal("9.00"))
        self.assertEqual(item.damage_quantity, Decimal("1.00"))
        self.assertEqual(item.dealer_price_snapshot, Decimal("658.00"))
        self.assertEqual(item.trade_price_snapshot, Decimal("675.00"))
        self.assertEqual(item.sale_price_snapshot, Decimal("680.00"))
        self.assertEqual(item.sale_value, Decimal("6120.00"))
        self.assertEqual(item.return_value, Decimal("1360.00"))
        self.assertEqual(item.damage_value, Decimal("680.00"))
        self.assertEqual(product.refresh_from_db(), None)
        self.assertEqual(product.selling_price, Decimal("675.00"))
        summary_after = self.client.get("/daily-summary/?year=2026&month=9")
        self.assertContains(summary_after, invoice_number)
        self.assertEqual(summary_after.context["totals"]["sales"], Decimal("6120.00"))
        self.assertEqual(summary_after.context["totals"]["damage"], Decimal("680.00"))
        route_id = sale.route_id
        monthly_after = self.client.get(f"/reports/monthly/?year=2026&month=9&route={route_id}")
        self.assertEqual(monthly_after.context["totals"]["sales"], Decimal("6120.00"))

    def test_finalized_invoice_pdf_exports_only_the_current_saved_invoice(self):
        sale = SalesTransaction.objects.create(
            dealer=self.dealer,
            date=date(2026, 10, 10),
            invoice_number="AE-20261010-0001",
            status=SalesTransaction.Status.FINALIZED,
            notes="Saved invoice note",
        )
        SalesItem.objects.create(
            transaction=sale,
            product=self.product,
            order_quantity=10,
            return_quantity=2,
            damage_quantity=1,
            free_product_quantity=1,
            discount=5,
        )
        PaymentReconciliation.objects.create(transaction=sale, cash=500, expenses=10, credit=100, discount=5, others=2)
        CurrencyCount.objects.create(transaction=sale, quantity_1000=1, quantity_100=2)
        pending = SalesTransaction.objects.create(
            dealer=self.dealer,
            date=date(2026, 10, 10),
            invoice_number="AE-20261010-0002",
            status=SalesTransaction.Status.PENDING,
        )

        detail = self.client.get(f"/sales/transactions/{sale.pk}/")
        self.assertContains(detail, f'href="/sales/transactions/{sale.pk}/pdf/"')
        response = self.client.get(f"/sales/transactions/{sale.pk}/pdf/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="AE-20261010-0001.pdf"')
        self.assertTrue(response.content.startswith(b"%PDF-"))
        self.assertEqual(self.client.get(f"/sales/transactions/{pending.pk}/pdf/").status_code, 404)
        if os.environ.get("RENDER_INVOICE_PDF"):
            Path("tmp/pdfs").mkdir(parents=True, exist_ok=True)
            Path("tmp/pdfs/finalized-invoice-pdf-preview.pdf").write_bytes(response.content)

    def test_price_only_invoice_edit_preserves_saved_quantities(self):
        route = Route.objects.get(route_name="Dhalua")
        sale = SalesTransaction.objects.create(route=route, date=date(2026, 9, 27))
        item = SalesItem.objects.create(
            transaction=sale,
            product=self.product,
            order_quantity=12,
            return_quantity=2,
            foc_quantity=1,
            free_product_quantity=3,
            damage_quantity=1,
            discount=5,
        )

        response = self.client.post(
            f"/sales/transactions/{sale.pk}/edit/",
            {
                "notes": "Price update only",
                f"dealer_price_{item.pk}": "85",
                f"trade_price_{item.pk}": "105",
                f"foc_price_{item.pk}": "7",
                f"sale_price_{item.pk}": "110",
                "cash": "0",
                "expenses": "0",
                "credit": "0",
                "discount": "0",
                "others": "0",
            },
        )

        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.order_quantity, Decimal("12.00"))
        self.assertEqual(item.return_quantity, Decimal("2.00"))
        self.assertEqual(item.foc_quantity, Decimal("1.00"))
        self.assertEqual(item.free_product_quantity, Decimal("3.00"))
        self.assertEqual(item.damage_quantity, Decimal("1.00"))
        self.assertEqual(item.discount, Decimal("5.00"))
        self.assertEqual(item.sale_price_snapshot, Decimal("110.00"))
        self.assertEqual(item.sale_value, Decimal("990.00"))

    def test_edit_uses_and_persists_invoice_price_snapshots_after_product_price_changes(self):
        route = Route.objects.get(route_name="Doulkhar")
        product = Product.objects.create(
            name="Snapshot Milk",
            dealer_price=Decimal("80"),
            trade_price=Decimal("100"),
            foc=Decimal("7"),
            selling_price=Decimal("675"),
        )
        sale = SalesTransaction.objects.create(route=route, date=date(2026, 9, 26))
        item = SalesItem.objects.create(transaction=sale, product=product, order_quantity=12)

        # Product Setup may change later, but the opened invoice must still
        # present the values saved with its line.
        product.dealer_price = Decimal("90")
        product.trade_price = Decimal("110")
        product.foc = Decimal("9")
        product.selling_price = Decimal("700")
        product.save()
        item.refresh_from_db()
        self.assertEqual(item.dealer_price_snapshot, Decimal("80.00"))
        self.assertEqual(item.trade_price_snapshot, Decimal("100.00"))
        self.assertEqual(item.foc_snapshot, Decimal("7.00"))
        self.assertEqual(item.sale_price_snapshot, Decimal("675.00"))

        edit_page = self.client.get(f"/sales/transactions/{sale.pk}/edit/")
        self.assertContains(edit_page, 'value="675.00"')
        response = self.client.post(
            f"/sales/transactions/{sale.pk}/edit/",
            {
                "notes": "Evening close-out",
                f"order_quantity_{item.pk}": "12",
                f"return_quantity_{item.pk}": "1",
                f"damage_quantity_{item.pk}": "1",
                f"foc_quantity_{item.pk}": "0",
                f"free_product_quantity_{item.pk}": "2",
                f"discount_{item.pk}": "15",
                f"dealer_price_{item.pk}": "82",
                f"trade_price_{item.pk}": "105",
                f"foc_price_{item.pk}": "8",
                f"sale_price_{item.pk}": "680",
                "cash": "6000",
                "expenses": "100",
                "credit": "500",
                "discount": "25",
                "others": "50",
            },
        )
        self.assertEqual(response.status_code, 302)

        sale.refresh_from_db()
        item.refresh_from_db()
        product.refresh_from_db()
        self.assertEqual(SalesTransaction.objects.filter(pk=sale.pk).count(), 1)
        self.assertEqual(item.order_quantity, Decimal("12.00"))
        self.assertEqual(item.return_quantity, Decimal("1.00"))
        self.assertEqual(item.damage_quantity, Decimal("1.00"))
        self.assertEqual(item.free_product_quantity, Decimal("2.00"))
        self.assertEqual(item.dealer_price_snapshot, Decimal("82.00"))
        self.assertEqual(item.trade_price_snapshot, Decimal("105.00"))
        self.assertEqual(item.foc_snapshot, Decimal("8.00"))
        self.assertEqual(item.sale_price_snapshot, Decimal("680.00"))
        self.assertEqual(item.sale_quantity, Decimal("10.00"))
        self.assertEqual(item.sale_value, Decimal("6800.00"))
        self.assertEqual(item.return_value, Decimal("680.00"))
        self.assertEqual(item.damage_value, Decimal("680.00"))
        self.assertEqual(item.free_product_value, Decimal("1360.00"))
        self.assertEqual(sale.grand_total_sale, Decimal("6800.00"))
        self.assertEqual(sale.total_discount, Decimal("40.00"))
        self.assertEqual(sale.net_sale, Decimal("5400.00"))
        self.assertEqual(sale.reconciliation.expenses, Decimal("100.00"))
        self.assertEqual(sale.reconciliation.shortage, Decimal("125.00"))
        self.assertEqual(sale.damages.get().value, Decimal("680.00"))
        # Editing an invoice must never write back to Product Setup.
        self.assertEqual(product.dealer_price, Decimal("90.00"))
        self.assertEqual(product.trade_price, Decimal("110.00"))
        self.assertEqual(product.foc, Decimal("9.00"))
        self.assertEqual(product.selling_price, Decimal("700.00"))

        refreshed_edit_page = self.client.get(f"/sales/transactions/{sale.pk}/edit/")
        self.assertContains(refreshed_edit_page, 'value="680.00"')
        for label in ("Dealer<br>price", "Trade<br>price", "FOC<br>price", "Sale<br>price", "Total sale<br>(Tk)"):
            self.assertContains(refreshed_edit_page, label)
        self.assertNotContains(refreshed_edit_page, "Order<br>Qty")
        self.assertNotContains(refreshed_edit_page, "Sale<br>Qty")
        summary = self.client.get("/daily-summary/?date=2026-09-26")
        self.assertEqual(summary.context["totals"]["sales"], Decimal("6800.00"))
        self.assertEqual(summary.context["totals"]["damage"], Decimal("680.00"))
        self.assertEqual(summary.context["totals"]["discount"], Decimal("40.00"))
        self.assertEqual(summary.context["totals"]["expenses"], Decimal("100.00"))
        self.assertEqual(summary.context["totals"]["shortage"], Decimal("125.00"))
        self.assertEqual(summary.context["totals"]["net"], Decimal("5400.00"))
        self.assertContains(summary, "Snapshot Milk")
        self.assertEqual(summary.context["product_details"][0]["sale"], Decimal("10.00"))
        self.assertEqual(summary.context["product_details"][0]["value"], Decimal("6800.00"))

        report = self.client.get(f"/reports/monthly/?year=2026&month=9&route={route.pk}")
        self.assertEqual(report.context["totals"]["sales"], Decimal("6800.00"))
        self.assertContains(report, "Snapshot Milk")

    def test_default_routes_are_in_weekday_order(self):
        self.assertEqual(
            list(Route.objects.values_list("route_name", flat=True)),
            ["Doulkhar", "Dhalua", "Boxganj", "Bangodda", "Nangalkot", "Bholaine"],
        )
        self.assertEqual(Route.objects.get(route_name="Bangodda").weekday, Route.TUESDAY)

    def test_daily_sales_creates_and_reuses_a_typeable_route(self):
        response = self.client.get("/sales/?date=2026-09-29")
        self.assertContains(response, 'id="route-name"')
        self.assertContains(response, 'value="Bangodda"')
        response = self.client.post(
            "/sales/",
            {
                "date": "2026-09-29",
                "route_name": "New Route",
                "invoice_number": "ROUTE-1",
                "product_id": [self.product.id],
                "order_quantity": ["2"],
                "return_quantity": ["0"],
                "foc_quantity": ["0"],
                "free_product_quantity": ["0"],
                "discount": ["0"],
                "damage_quantity": ["0"],
            }
        )
        self.assertEqual(response.status_code, 302)
        route = Route.objects.get(route_name="New Route")
        self.assertEqual(route.weekday, Route.TUESDAY)
        sale = SalesTransaction.objects.get(route=route)
        self.assertEqual(sale.invoice_number, "AE-20260929-0001")
        self.assertEqual(sale.route, route)
        self.assertEqual(sale.route_day, "Tuesday")
        self.assertIsNone(sale.dealer)
        entry = self.client.get("/sales/?date=2026-09-29")
        self.assertContains(entry, 'value="New Route"')
        self.assertContains(entry, 'value="Bangodda"')
        reused = self.client.post(
            "/sales/",
            {"date": "2026-10-03", "route_name": "New Route"},
        )
        self.assertEqual(reused.status_code, 302)
        self.assertEqual(SalesTransaction.objects.filter(route=route).count(), 2)

    def test_new_invoices_sequence_per_date_and_edit_preserves_number(self):
        route = Route.objects.get(route_name="Doulkhar")
        first = SalesTransaction.objects.create(route=route, date=date(2026, 9, 26))
        second = SalesTransaction.objects.create(route=route, date=date(2026, 9, 26))
        third = SalesTransaction.objects.create(route=route, date=date(2026, 9, 26))
        next_day = SalesTransaction.objects.create(route=route, date=date(2026, 9, 27))
        self.assertEqual(first.invoice_number, "AE-20260926-0001")
        self.assertEqual(second.invoice_number, "AE-20260926-0002")
        self.assertEqual(third.invoice_number, "AE-20260926-0003")
        self.assertEqual(next_day.invoice_number, "AE-20260927-0001")
        original = first.invoice_number
        first.notes = "Edited"
        first.save()
        self.assertEqual(first.invoice_number, original)

    def test_invoice_number_is_database_unique_and_preview_uses_date(self):
        route = Route.objects.get(route_name="Dhalua")
        SalesTransaction.objects.create(route=route, date=date(2026, 9, 26))
        response = self.client.get("/sales/invoice-preview/?date=2026-09-26")
        self.assertEqual(response.json()["invoice_number"], "AE-20260926-0002")
        with self.assertRaises(IntegrityError):
            SalesTransaction.objects.create(route=route, date=date(2026, 9, 26), invoice_number="AE-20260926-0001")

    def test_daily_sale_is_persisted_with_snapshots_and_summary_history(self):
        product = Product.objects.create(
            name="Diploma 1kg",
            category="Milk",
            ctn_size=12,
            dealer_price=Decimal("871.17"),
            trade_price=Decimal("893"),
            selling_price=Decimal("893"),
        )
        GodownStockReceipt.objects.create(product=product, received_ctn=100, reference="DIPLOMA-TEST-STOCK")
        response = self.client.post(
            "/sales/",
            {
                "date": "2026-09-27",
                "route_name": "Dhalua",
                "invoice_number": "should-be-ignored",
                "product_id": [product.id],
                "order_quantity": ["12"],
                "return_quantity": ["2"],
                "foc_quantity": ["0"],
                "free_product_quantity": ["0"],
                "discount": ["0"],
                "damage_quantity": ["0"],
                "cash": "1000",
                "expenses": "0",
                "credit": "0",
                "payment_discount": "0",
                "others": "0",
            },
        )
        self.assertEqual(response.status_code, 302)
        sale = SalesTransaction.objects.get(date=date(2026, 9, 27), route__route_name="Dhalua")
        item = sale.items.get()
        self.assertEqual(sale.invoice_number, "AE-20260927-0001")
        self.assertEqual(item.product_name_snapshot, "Diploma 1kg")
        self.assertEqual(item.category_snapshot, "Milk")
        self.assertEqual(item.ctn_size_snapshot, 12)
        self.assertEqual(item.sale_price_snapshot, Decimal("893.00"))
        self.assertEqual(item.order_quantity, Decimal("12.00"))
        self.assertEqual(item.return_quantity, Decimal("2.00"))
        self.assertEqual(item.sale_quantity, Decimal("10.00"))
        self.assertEqual(item.damage_quantity, Decimal("0.00"))
        self.assertContains(self.client.get("/daily-summary/?date=2026-09-27"), "Diploma 1kg")
        product.selling_price = Decimal("900")
        product.save()
        item.refresh_from_db()
        self.assertEqual(item.sale_price_snapshot, Decimal("893.00"))
        self.assertContains(self.client.get(f"/sales/products/{product.id}/history/"), sale.invoice_number)

    def test_route_names_are_case_insensitively_reused(self):
        Route.objects.create(route_name="Unique Route", weekday=Route.SATURDAY)
        with self.assertRaises(Exception):
            duplicate = Route(route_name="unique route", weekday=Route.SUNDAY)
            duplicate.full_clean()
class CurrencyCountIntegrationTests(TestCase):
    def setUp(self):
        self.dealer = Dealer.objects.create(name="Currency Dealer", code="CURRENCY", route=Route.objects.get(route_name="Dhalua"))
        self.product = Product.objects.create(name="Currency Milk", trade_price=Decimal("100"), selling_price=Decimal("100"))
        GodownStockReceipt.objects.create(product=self.product, received_ctn=100, reference="CURRENCY-TEST-STOCK")

    def currency_counts(self):
        return {
            "currency_count_1000": "16",
            "currency_count_500": "37",
            "currency_count_200": "7",
            "currency_count_100": "33",
            "currency_count_50": "12",
            "currency_count_20": "24",
            "currency_count_10": "21",
            "currency_count_5": "12",
            "currency_count_1": "2160",
        }

    def test_currency_count_saves_reopens_and_updates_reconciliation_cash(self):
        from .models import CurrencyCount

        response = self.client.post(
            "/sales/",
            {
                "date": "2026-10-01",
                "dealer": self.dealer.id,
                "invoice_number": "CURRENCY-1",
                "product_id": [self.product.id],
                "order_quantity": ["1"],
                "return_quantity": ["0"],
                "foc_quantity": ["0"],
                "free_product_quantity": ["0"],
                "damage_quantity": ["0"],
                "discount": ["0"],
                **self.currency_counts(),
            },
        )

        self.assertEqual(response.status_code, 302)
        sale = SalesTransaction.objects.get(date=date(2026, 10, 1), dealer=self.dealer)
        self.assertEqual(sale.currency_count.total_cash, Decimal("42710.00"))
        self.assertEqual(sale.reconciliation.cash, Decimal("42710.00"))
        self.assertEqual(sale.reconciliation.shortage, Decimal("-42610.00"))

        edit_page = self.client.get(f"/sales/transactions/{sale.pk}/edit/")
        self.assertContains(edit_page, 'value="16"')
        self.assertContains(edit_page, "42710.00")

        changed_counts = self.currency_counts()
        changed_counts["currency_count_1000"] = "17"
        response = self.client.post(
            f"/sales/transactions/{sale.pk}/edit/",
            {
                "currency_count_active": "1",
                "expenses": "0",
                "credit": "0",
                "discount": "0",
                "others": "0",
                **changed_counts,
            },
        )

        self.assertEqual(response.status_code, 302)
        sale.refresh_from_db()
        self.assertEqual(sale.currency_count.quantity_1000, 17)
        self.assertEqual(sale.currency_count.total_cash, Decimal("43710.00"))
        self.assertEqual(sale.reconciliation.cash, Decimal("43710.00"))
        self.assertEqual(sale.reconciliation.shortage, Decimal("-43610.00"))

        other_sale = SalesTransaction.objects.create(dealer=self.dealer, date="2026-10-02", invoice_number="CURRENCY-2")
        CurrencyCount.objects.create(transaction=other_sale, quantity_1000=1)
        sale.refresh_from_db()
        self.assertEqual(sale.currency_count.total_cash, Decimal("43710.00"))
        self.assertEqual(other_sale.currency_count.total_cash, Decimal("1000.00"))
class RouteEntryTests(TestCase):
    def test_new_invoice_uses_the_canonical_route_for_each_scheduled_day(self):
        for invoice_date, weekday, route_name in (
            ("2026-09-26", "Saturday", "Doulkhar"),
            ("2026-09-27", "Sunday", "Dhalua"),
            ("2026-09-28", "Monday", "Boxganj"),
            ("2026-09-29", "Tuesday", "Bangodda"),
            ("2026-09-30", "Wednesday", "Nangalkot"),
            ("2026-10-01", "Thursday", "Bholaine"),
        ):
            response = self.client.get(f"/sales/?date={invoice_date}")
            self.assertEqual(response.status_code, 200)
            self.assertContains(
                response,
                f'id="route-name" name="route_name" list="route-options" value="{route_name}"',
            )
            self.assertContains(response, f'<input id="route-day" value="{weekday}" readonly')
            self.assertContains(response, "Expected route for this date:")
            route_options = response.content.decode().split('<datalist id="route-options">', 1)[1].split("</datalist>", 1)[0]
            self.assertIn(f'<option value="{route_name}"></option>', route_options)
            for weekday_name in ("Saturday", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday"):
                self.assertNotIn(weekday_name, route_options)

    def test_existing_invoice_keeps_its_saved_route_and_route_day(self):
        route = Route.objects.get(route_name="Dhalua")
        sale = SalesTransaction.objects.create(route=route, route_day="Sunday", date=date(2026, 9, 28))

        edit = self.client.get(f"/sales/transactions/{sale.pk}/edit/")

        self.assertEqual(edit.status_code, 200)
        self.assertContains(edit, 'value="Dhalua"')
        self.assertContains(edit, 'value="Monday"')
        self.client.post(f"/sales/transactions/{sale.pk}/edit/", {"notes": "Reviewed"})
        sale.refresh_from_db()
        self.assertEqual(sale.route, route)
        self.assertEqual(sale.route_day, "Sunday")


class PendingSalesWorkflowTests(TestCase):
    def setUp(self):
        self.route = Route.objects.get(route_name="Dhalua")
        self.dealer = Dealer.objects.create(name="Pending Dealer", code="PENDING-TEST", route=self.route)
        self.product = Product.objects.create(name="Pending Milk", ctn_size=20, trade_price=Decimal("100"), selling_price=Decimal("100"))
        GodownStockReceipt.objects.create(product=self.product, received_ctn=1, reference="PENDING-TEST-STOCK")

    def pending_line_payload(self, item_id, product_id, order_quantity, *, save_action):
        return {
            "item_id": [item_id],
            "product_id": [product_id],
            "order_quantity": [order_quantity],
            "return_quantity": ["2"],
            "foc_quantity": ["0"],
            "free_product_quantity": ["1"],
            "damage_quantity": ["1"],
            "line_discount": ["5"],
            "cash": "0",
            "expenses": "0",
            "credit": "600",
            "discount": "0",
            "others": "0",
            "save_action": save_action,
        }

    def test_pending_invoice_edits_its_existing_line_and_finalizes_once(self):
        replacement = Product.objects.create(name="Pending Tea", ctn_size=10, trade_price=Decimal("50"), selling_price=Decimal("50"))
        GodownStockReceipt.objects.create(product=replacement, received_ctn=2, reference="PENDING-TEA-STOCK")
        response = self.client.post(
            "/daily-sales/",
            {
                "date": "2026-10-05",
                "route_name": self.route.route_name,
                "dealer": self.dealer.id,
                "product_id": [self.product.id],
                "order_quantity": ["10"],
                "return_quantity": ["0"],
                "foc_quantity": ["0"],
                "free_product_quantity": ["0"],
                "damage_quantity": ["1"],
                "discount": ["0"],
                "credit": "600",
                "save_action": "pending",
            },
        )
        self.assertEqual(response.status_code, 302)
        sale = SalesTransaction.objects.get(date=date(2026, 10, 5), route=self.route)
        self.assertEqual(sale.status, SalesTransaction.Status.PENDING)
        invoice_number = sale.invoice_number
        item = sale.items.get()
        self.assertEqual(sale.items.count(), 1)
        self.assertEqual(item.sale_price_snapshot, Decimal("100.00"))
        self.assertEqual(StockTransaction.objects.filter(reference=invoice_number).count(), 0)
        self.assertEqual(Damage.objects.filter(related_transaction=sale).count(), 0)
        self.assertEqual(stock_balances([self.product])[self.product.pk], Decimal("20"))
        self.assertEqual(dealer_due(self.dealer), Decimal("0"))
        summary = self.client.get("/daily-summary/?year=2026&month=10")
        self.assertNotContains(summary, invoice_number)
        pending_list = self.client.get("/daily-sales/pending/?date=2026-10-05")
        self.assertContains(pending_list, invoice_number)
        pending_edit = self.client.get(f"/sales/transactions/{sale.id}/edit/")
        self.assertEqual(pending_edit.status_code, 200)
        self.assertContains(pending_edit, 'data-action="edit-pending-row"')
        self.assertContains(pending_edit, 'data-action="save-pending-row"')

        response = self.client.post(
            f"/sales/transactions/{sale.id}/edit/",
            self.pending_line_payload(item.id, replacement.id, "12", save_action="pending"),
        )
        self.assertEqual(response.status_code, 302)
        sale.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(sale.status, SalesTransaction.Status.PENDING)
        self.assertEqual(sale.items.count(), 1)
        self.assertEqual(item.pk, sale.items.get().pk)
        self.assertEqual(item.product, replacement)
        self.assertEqual(item.order_quantity, Decimal("12.00"))
        self.assertEqual(item.sale_quantity, Decimal("9.00"))
        self.assertEqual(StockTransaction.objects.filter(reference=invoice_number).count(), 0)
        self.assertEqual(Damage.objects.filter(related_transaction=sale).count(), 0)
        self.assertEqual(stock_balances([replacement])[replacement.pk], Decimal("20"))
        self.assertEqual(dealer_due(self.dealer), Decimal("0"))

        response = self.client.post(
            f"/sales/transactions/{sale.id}/edit/",
            self.pending_line_payload(item.id, replacement.id, "12", save_action="finalize"),
        )
        self.assertEqual(response.status_code, 302)
        sale.refresh_from_db()
        self.assertEqual(sale.status, SalesTransaction.Status.FINALIZED)
        self.assertEqual(sale.invoice_number, invoice_number)
        item.refresh_from_db()
        self.assertEqual(item.return_quantity, Decimal("2.00"))
        self.assertEqual(item.damage_quantity, Decimal("1.00"))
        self.assertEqual(item.sale_quantity, Decimal("9.00"))
        self.assertEqual(StockTransaction.objects.filter(reference=invoice_number).count(), 3)
        self.assertEqual(Damage.objects.filter(related_transaction=sale).count(), 1)
        self.assertEqual(stock_balances([replacement])[replacement.pk], Decimal("10"))
        self.assertEqual(dealer_due(self.dealer), Decimal("500.00"))
        finalized_summary = self.client.get("/daily-summary/?year=2026&month=10")
        self.assertContains(finalized_summary, invoice_number)
        pending_list_after = self.client.get("/daily-sales/pending/?date=2026-10-05")
        self.assertNotContains(pending_list_after, invoice_number)
        finalized_edit = self.client.get(f"/sales/transactions/{sale.id}/edit/")
        self.assertNotContains(finalized_edit, 'data-action="edit-pending-row"')

        response = self.client.post(
            f"/sales/transactions/{sale.id}/edit/",
            {
                f"return_quantity_{item.id}": "2",
                f"damage_quantity_{item.id}": "1",
                f"free_product_quantity_{item.id}": "1",
                f"discount_{item.id}": "5",
                "cash": "0",
                "expenses": "0",
                "credit": "600",
                "discount": "0",
                "others": "0",
                "save_action": "finalize",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(StockTransaction.objects.filter(reference=invoice_number).count(), 3)

    def test_pending_invoice_can_add_and_remove_product_rows(self):
        added_product = Product.objects.create(name="Pending Yogurt", ctn_size=10, trade_price=Decimal("60"), selling_price=Decimal("60"))
        GodownStockReceipt.objects.create(product=added_product, received_ctn=2, reference="PENDING-YOGURT-STOCK")
        self.client.post(
            "/daily-sales/",
            {
                "date": "2026-10-06",
                "route_name": self.route.route_name,
                "product_id": [self.product.id],
                "order_quantity": ["2"],
                "return_quantity": ["0"],
                "foc_quantity": ["0"],
                "free_product_quantity": ["0"],
                "damage_quantity": ["0"],
                "discount": ["0"],
                "save_action": "pending",
            },
        )
        sale = SalesTransaction.objects.get(date=date(2026, 10, 6), route=self.route)
        item = sale.items.get()
        add_payload = {
            "item_id": [item.id, ""],
            "product_id": [self.product.id, added_product.id],
            "order_quantity": ["2", "3"],
            "return_quantity": ["0", "0"],
            "foc_quantity": ["0", "0"],
            "free_product_quantity": ["0", "0"],
            "damage_quantity": ["0", "0"],
            "line_discount": ["0", "0"],
            "save_action": "pending",
        }
        response = self.client.post(f"/sales/transactions/{sale.id}/edit/", add_payload)
        self.assertEqual(response.status_code, 302)
        sale.refresh_from_db()
        self.assertEqual(sale.items.count(), 2)
        self.assertEqual(sale.items.get(product=self.product).pk, item.pk)

        remove_payload = {
            "item_id": [item.id],
            "product_id": [self.product.id],
            "order_quantity": ["2"],
            "return_quantity": ["0"],
            "foc_quantity": ["0"],
            "free_product_quantity": ["0"],
            "damage_quantity": ["0"],
            "line_discount": ["0"],
            "save_action": "pending",
        }
        response = self.client.post(f"/sales/transactions/{sale.id}/edit/", remove_payload)
        self.assertEqual(response.status_code, 302)
        sale.refresh_from_db()
        self.assertEqual(sale.items.count(), 1)
        self.assertEqual(sale.items.get().pk, item.pk)
        self.assertEqual(StockTransaction.objects.filter(reference=sale.invoice_number).count(), 0)
