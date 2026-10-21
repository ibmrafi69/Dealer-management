from decimal import Decimal

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

    def test_credit_person_edit_page_opens_and_saves_successfully(self):
        route = Route.objects.filter(group=self.legacy_group).first()
        dealer = Dealer.objects.create(group=self.legacy_group, name="Initial Store", code="INIT-01", route=route, opening_due=50)

        # Test GET edit page in own group
        response = self.client.get(f"/credit/dealers/{dealer.pk}/edit/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Edit Dealer")
        self.assertContains(response, "Initial Store")
        self.assertContains(response, "INIT-01")

        # Test POST saving valid changes in own group
        post_data = {
            "name": "Updated Store Name",
            "route": route.pk,
            "address": "123 Main Road",
            "location": "Central Bazar",
            "phone": "01700000000",
            "contact_person": "Rahim",
            "opening_due": "75.00",
            "memo": "Deliver before noon",
        }
        response = self.client.post(f"/credit/dealers/{dealer.pk}/edit/", post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, f"/credit/dealers/{dealer.pk}/")

        dealer.refresh_from_db()
        self.assertEqual(dealer.name, "Updated Store Name")
        self.assertEqual(dealer.address, "123 Main Road")
        self.assertEqual(dealer.location, "Central Bazar")
        self.assertEqual(dealer.phone, "01700000000")
        self.assertEqual(dealer.contact_person, "Rahim")
        self.assertEqual(dealer.opening_due, Decimal("75.00"))
        self.assertEqual(dealer.memo, "Deliver before noon")
        self.assertEqual(dealer.group, self.legacy_group)

    def test_cross_group_switching_and_isolation_for_credit_person(self):
        bd_group = Group.objects.get(name="BD Foods")
        nzd_route = Route.objects.filter(group=self.legacy_group).first()
        nzd_dealer = Dealer.objects.create(group=self.legacy_group, name="NZD Sole Dealer", code="NZD-99", route=nzd_route, opening_due=200)

        # 1. Switch group to BD Foods from Credit Management detail/edit URL
        switch_response = self.client.post("/groups/switch/", {
            "group_id": bd_group.pk,
            "next": f"/credit/dealers/{nzd_dealer.pk}/edit/",
        })
        self.assertEqual(switch_response.status_code, 302)
        # Verify sanitized next URL does NOT carry foreign dealer ID into new group
        self.assertEqual(switch_response.url, "/credit/")
        self.assertEqual(self.client.session["current_group_id"], bd_group.pk)

        # 2. Attempting to GET NZD dealer edit page while in BD Foods is blocked
        foreign_edit = self.client.get(f"/credit/dealers/{nzd_dealer.pk}/edit/", follow=True)
        self.assertEqual(foreign_edit.status_code, 200)
        self.assertEqual(foreign_edit.redirect_chain, [("/credit/", 302)])
        self.assertContains(foreign_edit, "belongs to group")
        self.assertContains(foreign_edit, "New Zealand Dairy")
        self.assertContains(foreign_edit, "Please switch to")
        # Ensure foreign dealer is NOT displayed in BD Foods credit list
        self.assertNotContains(foreign_edit, f"/credit/dealers/{nzd_dealer.pk}/")

        # 3. Attempting to POST edit to NZD dealer while in BD Foods is rejected
        blocked_edit = self.client.post(f"/credit/dealers/{nzd_dealer.pk}/edit/", {
            "name": "Hacked Name",
            "route": nzd_route.pk,
        })
        self.assertEqual(blocked_edit.status_code, 302)
        self.assertEqual(blocked_edit.url, "/credit/")
        nzd_dealer.refresh_from_db()
        self.assertEqual(nzd_dealer.name, "NZD Sole Dealer")  # Record unchanged

        # 4. Attempting to POST payment to NZD dealer while in BD Foods is rejected
        blocked_pay = self.client.post(f"/credit/dealers/{nzd_dealer.pk}/payment/", {
            "payment_date": "2026-10-21",
            "amount": "100.00",
            "method": DealerPayment.CASH,
        })
        self.assertEqual(blocked_pay.status_code, 302)
        self.assertEqual(blocked_pay.url, "/credit/")
        self.assertEqual(DealerPayment.objects.filter(group=bd_group).count(), 0)
        self.assertEqual(nzd_dealer.payments.count(), 0)
        self.assertEqual(nzd_dealer.current_due, Decimal("200.00"))

        # 5. Invalid / non-existent dealer ID
        missing_resp = self.client.get("/credit/dealers/99999/edit/", follow=True)
        self.assertEqual(missing_resp.status_code, 200)
        self.assertEqual(missing_resp.redirect_chain, [("/credit/", 302)])
        self.assertContains(missing_resp, "The requested dealer was not found.")



class GroupWorkflowTests(TestCase):
    def setUp(self):
        self.nzd_group = Group.objects.get(name="New Zealand Dairy")
        self.bd_group = Group.objects.get(name="BD Foods")

    def test_group_select_home_screen_displays_groups_and_actions(self):
        # Root URL and /groups/ both route to Group Selection dashboard
        for url in ["/", "/groups/"]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Dealer Management")
            self.assertContains(response, "Select a business group to continue")
            self.assertContains(response, "New Zealand Dairy")
            self.assertContains(response, "BD Foods")
            self.assertContains(response, "Open Group")
            self.assertContains(response, "Create New Group")

    def test_open_group_sets_session_and_redirects_to_dashboard(self):
        response = self.client.post(f"/groups/{self.bd_group.pk}/open/")
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, "/dashboard/")
        self.assertEqual(self.client.session.get("current_group_id"), self.bd_group.pk)

    def test_open_invalid_group_redirects_safely_without_crash(self):
        response = self.client.post("/groups/99999/open/", follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain, [("/groups/", 302)])
        self.assertContains(response, "The selected business group is not available.")

    def test_logout_clears_session_and_preserves_database_data(self):
        # Set session to BD Foods
        session = self.client.session
        session["current_group_id"] = self.bd_group.pk
        session.save()

        # Logout
        response = self.client.post("/logout/", follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain, [("/groups/", 302)])
        self.assertIsNone(self.client.session.get("current_group_id"))
        self.assertContains(response, "You have been logged out.")

        # Ensure all database records are completely intact
        self.assertTrue(Group.objects.filter(pk=self.bd_group.pk).exists())
        self.assertTrue(Group.objects.filter(pk=self.nzd_group.pk).exists())

    def test_create_new_group_validates_duplicates_and_allows_immediate_use(self):
        # 1. Duplicate group name (case-insensitive) is rejected
        dup_resp = self.client.post("/groups/create/", {"name": "new zealand dairy"})
        self.assertEqual(dup_resp.status_code, 200)
        self.assertContains(dup_resp, "A group with this name already exists.")

        # 2. Blank group name is rejected
        blank_resp = self.client.post("/groups/create/", {"name": "   "})
        self.assertEqual(blank_resp.status_code, 200)
        self.assertContains(blank_resp, "Group name is required.")

        # 3. Valid new group creates record, sets session, and opens dashboard
        create_resp = self.client.post("/groups/create/", {"name": "Sunrise Agro"})
        self.assertEqual(create_resp.status_code, 302)
        self.assertRedirects(create_resp, "/dashboard/")
        created = Group.objects.get(name="Sunrise Agro")
        self.assertEqual(self.client.session.get("current_group_id"), created.pk)

    def test_pending_sales_invoices_preserved_and_isolated_across_group_switching(self):
        nzd_route = Route.objects.filter(group=self.nzd_group).first()
        bd_route = Route.objects.filter(group=self.bd_group).first()
        nzd_dealer = Dealer.objects.create(group=self.nzd_group, name="NZD Pending Dealer", code="P-01", route=nzd_route)
        bd_dealer = Dealer.objects.create(group=self.bd_group, name="BD Pending Dealer", code="P-02", route=bd_route)

        # Create pending invoice in NZD
        nzd_pending = SalesTransaction.objects.create(
            group=self.nzd_group,
            dealer=nzd_dealer,
            route=nzd_route,
            date="2026-10-21",
            invoice_number="INV-NZD-PENDING",
            status=SalesTransaction.Status.PENDING,
        )

        # Switch to BD Foods using open_group
        self.client.post(f"/groups/{self.bd_group.pk}/open/")
        self.assertEqual(self.client.session.get("current_group_id"), self.bd_group.pk)

        # Verify NZD pending invoice is NOT visible in BD Foods pending list
        bd_pending_view = self.client.get("/daily-sales/pending/?date=2026-10-21")
        self.assertEqual(bd_pending_view.status_code, 200)
        self.assertNotContains(bd_pending_view, "INV-NZD-PENDING")

        # Create pending invoice in BD Foods
        bd_pending = SalesTransaction.objects.create(
            group=self.bd_group,
            dealer=bd_dealer,
            route=bd_route,
            date="2026-10-21",
            invoice_number="INV-BD-PENDING",
            status=SalesTransaction.Status.PENDING,
        )

        # In BD Foods, BD pending is visible, NZD pending is not
        bd_pending_view2 = self.client.get("/daily-sales/pending/?date=2026-10-21")
        self.assertContains(bd_pending_view2, "INV-BD-PENDING")
        self.assertNotContains(bd_pending_view2, "INV-NZD-PENDING")

        # Switch back to NZD
        self.client.post(f"/groups/{self.nzd_group.pk}/open/")
        self.assertEqual(self.client.session.get("current_group_id"), self.nzd_group.pk)

        # In NZD, NZD pending is intact and visible; BD pending is not
        nzd_pending_view = self.client.get("/daily-sales/pending/?date=2026-10-21")
        self.assertContains(nzd_pending_view, "INV-NZD-PENDING")
        self.assertNotContains(nzd_pending_view, "INV-BD-PENDING")

    def test_landing_page_enter_system_button_links_to_group_select(self):
        landing_resp = self.client.get("/landing/")
        self.assertEqual(landing_resp.status_code, 200)
        self.assertContains(landing_resp, "/groups/")
