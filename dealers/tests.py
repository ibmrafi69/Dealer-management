from django.test import TestCase
from django.core.exceptions import ValidationError

from godown_stock.models import GodownStockReceipt
from products.models import Product
from sales.models import PaymentReconciliation, SalesItem, SalesTransaction

from .models import Dealer, DealerPayment, Group, Route
from .credit import dealer_ledger


class DealerTests(TestCase):
    def test_dealer_can_be_created(self):
        dealer = Dealer.objects.create(name="Central Store", code="CENTRAL")
        self.assertEqual(str(dealer), "Central Store (CENTRAL)")

    def test_credit_ledger_uses_finalized_credit_and_payments(self):
        group = Group.objects.get(name="New Zealand Dairy")
        route = Route.objects.filter(group=group).first()
        dealer = Dealer.objects.create(name="Credit Store", code="CREDIT", route=route, opening_due=100)
        product = Product.objects.create(group=group, name="Credit Product", category=Product.MILK, selling_price=100)
        finalized = SalesTransaction.objects.create(group=group, dealer=dealer, route=route, date="2026-10-01", invoice_number="CREDIT-1", status=SalesTransaction.Status.FINALIZED)
        SalesItem.objects.create(group=group, transaction=finalized, product=product, order_quantity=100)
        PaymentReconciliation.objects.create(transaction=finalized, cash=9000, credit=1000)
        pending = SalesTransaction.objects.create(group=group, dealer=dealer, route=route, date="2026-10-01", invoice_number="CREDIT-PENDING", status=SalesTransaction.Status.PENDING)
        SalesItem.objects.create(group=group, transaction=pending, product=product, order_quantity=100)
        self.assertEqual(dealer.current_due, 1100)
        DealerPayment.objects.create(group=group, dealer=dealer, payment_date="2026-10-01", amount=500, reference="PAY-1")
        self.assertEqual(dealer.current_due, 600)
        self.assertEqual([row["type"] for row in dealer_ledger(dealer)], ["Opening Due", "Invoice", "Payment"])

    def test_credit_management_pages_and_payment_form_are_group_scoped(self):
        group = Group.objects.get(name="New Zealand Dairy")
        route = Route.objects.filter(group=group).first()
        dealer = Dealer.objects.create(name="Page Store", code="PAGE", route=route, opening_due=100)
        response = self.client.get("/credit/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Page Store")
        self.assertContains(response, "New Zealand Dairy")
        self.assertEqual(self.client.get(f"/credit/dealers/{dealer.pk}/").status_code, 200)
        response = self.client.post(f"/credit/dealers/{dealer.pk}/payment/", {"payment_date": "2026-10-01", "amount": "40", "method": DealerPayment.CASH, "reference": "PAGE-1"})
        self.assertEqual(response.status_code, 302)
        dealer.refresh_from_db()
        self.assertEqual(dealer.current_due, 60)
        response = self.client.post(f"/credit/dealers/{dealer.pk}/credit/", {"credit_date": "2026-10-01", "amount": "40", "reference": "Manual delivery credit", "notes": "Prior delivery"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(dealer.current_due, 100)
        self.assertContains(self.client.get(f"/credit/dealers/{dealer.pk}/"), "Manual delivery credit")

    def test_new_dealer_code_is_generated_from_current_group(self):
        group = Group.objects.get(name="New Zealand Dairy")
        route = Route.objects.filter(group=group).first()
        self.assertEqual(self.client.get("/credit/dealers/new/").status_code, 200)
        response = self.client.post("/credit/dealers/new/", {"name": "Generated Code Store", "route": route.pk, "opening_due": "0"})
        self.assertEqual(response.status_code, 302)
        dealer = Dealer.objects.get(name="Generated Code Store")
        self.assertRegex(dealer.code, r"^NZD-\d{4}$")


class GroupIsolationTests(TestCase):
    def setUp(self):
        self.legacy_group = Group.objects.get(name="New Zealand Dairy")

    def switch_to(self, group):
        response = self.client.post("/groups/switch/", {"group_id": group.pk, "next": "/dashboard/"})
        self.assertEqual(response.status_code, 302)

    def test_new_group_is_empty_and_becomes_current(self):
        response = self.client.post("/groups/create/", {"name": "ABC Foods"})
        self.assertEqual(response.status_code, 302)
        group = Group.objects.get(name="ABC Foods")
        self.assertEqual(group.products.count(), 0)
        self.assertEqual(group.sales_transactions.count(), 0)
        self.assertEqual(group.stock_receipts.count(), 0)
        self.assertEqual(self.client.session["current_group_id"], group.pk)

    def test_products_sales_stock_and_reports_are_isolated(self):
        other_group = Group.objects.create(name="XYZ Dairy")
        legacy_product = Product.objects.create(
            group=self.legacy_group,
            name="Milk 500ml",
            category=Product.MILK,
            ctn_size=12,
            selling_price=10,
        )
        other_product = Product.objects.create(
            group=other_group,
            name="Milk 500ml",
            category=Product.MILK,
            ctn_size=24,
            selling_price=20,
        )
        legacy_route = Route.objects.create(group=self.legacy_group, route_name="NZD Route", weekday=Route.MONDAY)
        other_route = Route.objects.create(group=other_group, route_name="XYZ Route", weekday=Route.MONDAY)
        legacy_sale = SalesTransaction.objects.create(
            group=self.legacy_group,
            route=legacy_route,
            date="2026-09-30",
            invoice_number="NZD-1",
        )
        SalesItem.objects.create(group=self.legacy_group, transaction=legacy_sale, product=legacy_product, order_quantity=2)
        GodownStockReceipt.objects.create(group=self.legacy_group, product=legacy_product, received_ctn=1)
        other_sale = SalesTransaction.objects.create(
            group=other_group,
            route=other_route,
            date="2026-09-30",
            invoice_number="XYZ-1",
        )
        SalesItem.objects.create(group=other_group, transaction=other_sale, product=other_product, order_quantity=3)
        GodownStockReceipt.objects.create(group=other_group, product=other_product, received_ctn=1)

        self.switch_to(other_group)
        self.assertContains(self.client.get("/product-setup/"), "Milk 500ml")
        daily_sales = self.client.get("/daily-sales/")
        self.assertContains(daily_sales, f'<option value="{other_product.pk}"')
        self.assertNotRegex(daily_sales.content.decode(), rf'<option value="{legacy_product.pk}" data-category=')
        stock = self.client.get("/godown-stock/")
        self.assertContains(stock, "Milk 500ml")
        self.assertEqual(self.client.get(f"/sales/transactions/{legacy_sale.pk}/").status_code, 404)
        summary = self.client.get("/daily-summary/?date=2026-09-30")
        self.assertContains(summary, "XYZ-1")
        self.assertNotContains(summary, "NZD-1")

    def test_product_names_are_reusable_between_groups_but_not_within_group(self):
        other_group = Group.objects.create(name="Fresh Foods")
        Product.objects.create(group=self.legacy_group, name="Shared Name", category=Product.MILK)
        Product.objects.create(group=other_group, name="Shared Name", category=Product.MILK)
        duplicate = Product(group=self.legacy_group, name="shared name", category=Product.MILK)
        with self.assertRaises(Exception):
            duplicate.full_clean()

    def test_empty_group_can_be_deleted_and_session_falls_back(self):
        response = self.client.post("/groups/create/", {"name": "Temporary Empty Group"})
        self.assertEqual(response.status_code, 302)
        empty_group = Group.objects.get(name="Temporary Empty Group")
        dashboard = self.client.get("/dashboard/")
        self.assertContains(dashboard, "Delete Group")

        response = self.client.post(
            f"/groups/{empty_group.pk}/delete/",
            {"next": "/dashboard/"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Group.objects.filter(pk=empty_group.pk).exists())
        self.assertEqual(self.client.session["current_group_id"], self.legacy_group.pk)
        self.assertNotContains(self.client.get("/dashboard/"), "Temporary Empty Group")

    def test_groups_with_business_data_cannot_be_deleted(self):
        bd_group = Group.objects.get(name="BD Foods")
        response = self.client.post(f"/groups/{bd_group.pk}/delete/", {"next": "/dashboard/"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Group.objects.filter(pk=bd_group.pk).exists())
        with self.assertRaises(ValidationError):
            bd_group.delete()
        with self.assertRaises(ValidationError):
            self.legacy_group.delete()