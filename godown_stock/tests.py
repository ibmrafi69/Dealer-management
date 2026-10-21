from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from dealers.models import Group
from products.models import Category, Product
from sales.models import SalesItem, SalesTransaction

from .models import GodownStockReceipt
from .services import stock_display, stock_history, stock_rows


class GodownStockTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Godown Test Product",
            category=Product.GHEE,
            ctn_size=24,
            trade_price=100,
            selling_price=100,
        )

    def balance_for_product(self):
        return stock_rows([self.product])[0]["balance_pieces"]

    def test_receipt_persists_total_pieces_and_formats_cartons(self):
        receipt = GodownStockReceipt.objects.create(
            product=self.product,
            received_ctn=2,
            received_pcs=5,
            reference="CH-01",
        )

        self.assertEqual(receipt.total_pieces, 53)
        self.assertEqual(self.balance_for_product(), Decimal("53"))
        self.assertEqual(stock_display(Decimal("28"), self.product.ctn_size), "1 CTN 4 PCS")

    def test_only_finalized_invoices_change_stock_and_returns_are_added_back(self):
        GodownStockReceipt.objects.create(product=self.product, received_ctn=2)
        finalized = SalesTransaction.objects.create(
            date=date(2026, 9, 28),
            invoice_number="GODOWN-FINAL",
            status=SalesTransaction.Status.FINALIZED,
        )
        item = SalesItem.objects.create(
            transaction=finalized,
            product=self.product,
            order_quantity=Decimal("1.25"),  # Daily Sales stores quantities in pieces.
        )
        pending = SalesTransaction.objects.create(
            date=date(2026, 9, 28),
            invoice_number="GODOWN-PENDING",
            status=SalesTransaction.Status.PENDING,
        )
        SalesItem.objects.create(transaction=pending, product=self.product, order_quantity=Decimal("1.00"))

        self.assertEqual(self.balance_for_product(), Decimal("46.75"))
        self.assertEqual(stock_display(self.balance_for_product(), self.product.ctn_size), "1 CTN 22.75 PCS")

        item.return_quantity = Decimal("0.42")
        item.save()

        self.assertEqual(self.balance_for_product(), Decimal("47.17"))
        movements = [event["movement"] for event in stock_history(self.product)]
        self.assertIn("Finalized dispatch", movements)
        self.assertIn("Finalized return", movements)
        self.assertNotIn("GODOWN-PENDING", [event["reference"] for event in stock_history(self.product)])


class BulkStockEntryTests(TestCase):
    def setUp(self):
        self.group = Group.objects.create(name="Bulk Entry Group")
        self.category = Category.objects.create(group=self.group, name="Bulk Entry Category")
        self.product_one = Product.objects.create(name="Bulk Product One", group=self.group, category=self.category, ctn_size=24)
        self.product_two = Product.objects.create(name="Bulk Product Two", group=self.group, category=self.category, ctn_size=12)
        self.inactive_product = Product.objects.create(
            name="Inactive Bulk Product", group=self.group, category=self.category, ctn_size=6, active=False
        )
        self.other_group = Group.objects.create(name="Other Bulk Entry Group")
        self.other_category = Category.objects.create(group=self.other_group, name="Other Bulk Category")
        self.other_product = Product.objects.create(
            name="Other Group Bulk Product", group=self.other_group, category=self.other_category, ctn_size=8
        )
        session = self.client.session
        session["current_group_id"] = self.group.pk
        session.save()
        self.url = reverse("godown-add-stock")

    def submission_data(self, token, rows, reference="BULK-RECEIPT-1", received_at="2026-10-20T12:00"):
        data = {
            "submission_token": token,
            "received_at": received_at,
            "reference": reference,
            "notes": "Bulk delivery",
            "receipts-TOTAL_FORMS": str(len(rows)),
            "receipts-INITIAL_FORMS": "0",
            "receipts-MIN_NUM_FORMS": "1",
            "receipts-MAX_NUM_FORMS": "1000",
        }
        for index, (product, cartons, pieces) in enumerate(rows):
            data.update(
                {
                    f"receipts-{index}-product": product.pk,
                    f"receipts-{index}-received_ctn": cartons,
                    f"receipts-{index}-received_pcs": pieces,
                }
            )
        return data

    def submission_token(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return response.context["submission_token"]

    def test_bulk_entry_saves_all_rows_uses_product_conversions_and_is_idempotent(self):
        data = self.submission_data(
            self.submission_token(),
            [(self.product_one, 2, 5), (self.product_two, 1, 3)],
        )

        response = self.client.post(self.url, data)

        self.assertRedirects(response, reverse("godown-stock"))
        receipts = list(GodownStockReceipt.objects.filter(group=self.group).order_by("product__name"))
        self.assertEqual([(receipt.product, receipt.total_pieces) for receipt in receipts], [(self.product_one, 53), (self.product_two, 15)])
        self.assertEqual(receipts[0].reference, "BULK-RECEIPT-1")

        repeated_response = self.client.post(self.url, data)

        self.assertRedirects(repeated_response, reverse("godown-stock"))
        self.assertEqual(GodownStockReceipt.objects.filter(group=self.group).count(), 2)

    def test_invalid_or_duplicate_rows_save_nothing(self):
        invalid_data = self.submission_data(
            self.submission_token(),
            [(self.product_one, 1, 0), (self.product_two, 0, self.product_two.ctn_size)],
        )

        invalid_response = self.client.post(self.url, invalid_data)

        self.assertEqual(invalid_response.status_code, 200)
        self.assertContains(invalid_response, "Partial pieces must be smaller")
        self.assertFalse(GodownStockReceipt.objects.filter(group=self.group).exists())

        duplicate_data = self.submission_data(
            self.submission_token(),
            [(self.product_one, 1, 0), (self.product_one, 0, 2)],
        )

        duplicate_response = self.client.post(self.url, duplicate_data)

        self.assertEqual(duplicate_response.status_code, 200)
        self.assertContains(duplicate_response, "already included in another row")
        self.assertFalse(GodownStockReceipt.objects.filter(group=self.group).exists())

    def test_bulk_entry_only_accepts_active_products_in_the_current_group(self):
        page = self.client.get(self.url)

        self.assertContains(page, self.product_one.name)
        self.assertNotContains(page, self.inactive_product.name)
        self.assertNotContains(page, self.other_product.name)

        inactive_data = self.submission_data(self.submission_token(), [(self.inactive_product, 1, 0)])
        inactive_response = self.client.post(self.url, inactive_data)

        self.assertEqual(inactive_response.status_code, 200)
        self.assertContains(inactive_response, "Select a valid choice")
        self.assertFalse(GodownStockReceipt.objects.filter(group=self.group).exists())

        data = self.submission_data(self.submission_token(), [(self.other_product, 1, 0)])
        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a valid choice")
        self.assertFalse(GodownStockReceipt.objects.filter(group=self.group).exists())

    def test_bulk_entry_requires_a_challan_number_and_entry_date(self):
        missing_challan = self.submission_data(
            self.submission_token(),
            [(self.product_one, 1, 0)],
            reference="",
        )

        challan_response = self.client.post(self.url, missing_challan)

        self.assertEqual(challan_response.status_code, 200)
        self.assertContains(challan_response, "This field is required")
        self.assertFalse(GodownStockReceipt.objects.filter(group=self.group).exists())

        missing_date = self.submission_data(
            self.submission_token(),
            [(self.product_one, 1, 0)],
            received_at="",
        )

        date_response = self.client.post(self.url, missing_date)

        self.assertEqual(date_response.status_code, 200)
        self.assertContains(date_response, "This field is required")
        self.assertFalse(GodownStockReceipt.objects.filter(group=self.group).exists())

    def test_challan_history_groups_receipts_and_shows_their_products(self):
        challan = "CHALLAN-2026-100"
        response = self.client.post(
            self.url,
            self.submission_data(
                self.submission_token(),
                [(self.product_one, 2, 5), (self.product_two, 1, 3)],
                reference=challan,
            ),
        )
        self.assertRedirects(response, reverse("godown-stock"))
        foreign_receipt = GodownStockReceipt.objects.create(
            group=self.other_group,
            product=self.other_product,
            received_ctn=1,
            reference=challan,
        )

        history_response = self.client.get(reverse("godown-stock-history"))

        self.assertEqual(history_response.status_code, 200)
        challans = list(history_response.context["challans"])
        self.assertEqual(len(challans), 1)
        self.assertEqual(challans[0]["reference"], challan)
        self.assertEqual(challans[0]["entry_date"].isoformat(), "2026-10-20")
        self.assertEqual(challans[0]["product_count"], 2)
        self.assertEqual(challans[0]["total_pieces"], 68)
        self.assertContains(history_response, "2 products")
        self.assertContains(history_response, "68 PCS")

        detail_response = self.client.get(
            reverse("godown-stock-history-challan", args=[challans[0]["first_receipt_id"]])
        )

        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, challan)
        self.assertContains(detail_response, self.product_one.name)
        self.assertContains(detail_response, self.product_two.name)
        self.assertContains(detail_response, "2 CTN")
        self.assertContains(detail_response, "1 CTN")
        self.assertContains(detail_response, "53 PCS")
        self.assertContains(detail_response, "15 PCS")
        # Accessing another group's challan is safely redirected without leaking data
        foreign_response = self.client.get(reverse("godown-stock-history-challan", args=[foreign_receipt.pk]))
        self.assertRedirects(foreign_response, reverse("godown-stock-history"))

    def test_bulk_entry_ignores_completely_empty_unused_rows(self):
        token = self.submission_token()
        data = {
            "submission_token": token,
            "received_at": "2026-10-20T12:00",
            "reference": "CH-EMPTY-ROWS",
            "notes": "Testing blank rows",
            "receipts-TOTAL_FORMS": "3",
            "receipts-INITIAL_FORMS": "0",
            "receipts-MIN_NUM_FORMS": "0",
            "receipts-MAX_NUM_FORMS": "1000",
            "receipts-0-product": str(self.product_one.pk),
            "receipts-0-received_ctn": "2",
            "receipts-0-received_pcs": "0",
            "receipts-1-product": "",
            "receipts-1-received_ctn": "0",
            "receipts-1-received_pcs": "0",
            "receipts-2-product": "",
            "receipts-2-received_ctn": "",
            "receipts-2-received_pcs": "",
        }
        response = self.client.post(self.url, data)
        self.assertRedirects(response, reverse("godown-stock"))
        receipts = list(GodownStockReceipt.objects.filter(group=self.group))
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0].product, self.product_one)
        self.assertEqual(receipts[0].total_pieces, 48)

    def test_bulk_entry_rejects_row_with_quantity_but_no_product(self):
        token = self.submission_token()
        data = {
            "submission_token": token,
            "received_at": "2026-10-20T12:00",
            "reference": "CH-NO-PRODUCT",
            "notes": "Testing missing product",
            "receipts-TOTAL_FORMS": "2",
            "receipts-INITIAL_FORMS": "0",
            "receipts-MIN_NUM_FORMS": "0",
            "receipts-MAX_NUM_FORMS": "1000",
            "receipts-0-product": str(self.product_one.pk),
            "receipts-0-received_ctn": "2",
            "receipts-0-received_pcs": "0",
            "receipts-1-product": "",
            "receipts-1-received_ctn": "5",
            "receipts-1-received_pcs": "0",
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please select a product for every stock-entry row containing a quantity.")
        self.assertFalse(GodownStockReceipt.objects.filter(group=self.group).exists())

    def test_bulk_entry_rejects_selected_product_with_zero_quantity(self):
        token = self.submission_token()
        data = {
            "submission_token": token,
            "received_at": "2026-10-20T12:00",
            "reference": "CH-ZERO-QTY",
            "notes": "Testing zero quantity",
            "receipts-TOTAL_FORMS": "1",
            "receipts-INITIAL_FORMS": "0",
            "receipts-MIN_NUM_FORMS": "0",
            "receipts-MAX_NUM_FORMS": "1000",
            "receipts-0-product": str(self.product_one.pk),
            "receipts-0-received_ctn": "0",
            "receipts-0-received_pcs": "0",
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter at least one carton or one piece.")
        self.assertFalse(GodownStockReceipt.objects.filter(group=self.group).exists())


    def test_challan_and_product_history_group_isolation_and_error_handling(self):
        # 1. Challan opens successfully when accessed in its owning group
        challan_ref = "OWNING-CHALLAN-01"
        receipt = GodownStockReceipt.objects.create(
            group=self.group,
            product=self.product_one,
            received_ctn=3,
            received_pcs=0,
            reference=challan_ref,
        )
        owning_response = self.client.get(reverse("godown-stock-history-challan", args=[receipt.pk]))
        self.assertEqual(owning_response.status_code, 200)
        self.assertContains(owning_response, challan_ref)
        self.assertContains(owning_response, self.product_one.name)

        # Product history opens successfully in its owning group
        product_history_response = self.client.get(reverse("godown-stock-history-product", args=[self.product_one.pk]))
        self.assertEqual(product_history_response.status_code, 200)
        self.assertContains(product_history_response, self.product_one.name)
        self.assertContains(product_history_response, challan_ref)

        # Inactive product's history can still be viewed in its owning group
        inactive_receipt = GodownStockReceipt.objects.create(
            group=self.group,
            product=self.inactive_product,
            received_ctn=1,
            received_pcs=0,
            reference="INACTIVE-CHALLAN",
        )
        inactive_history_response = self.client.get(reverse("godown-stock-history-product", args=[self.inactive_product.pk]))
        self.assertEqual(inactive_history_response.status_code, 200)
        self.assertContains(inactive_history_response, self.inactive_product.name)

        # 2. Accessing another group's challan from the wrong group is handled safely and does not leak data
        foreign_receipt = GodownStockReceipt.objects.create(
            group=self.other_group,
            product=self.other_product,
            received_ctn=5,
            received_pcs=0,
            reference="FOREIGN-CHALLAN-SECRET",
        )
        foreign_challan_response = self.client.get(reverse("godown-stock-history-challan", args=[foreign_receipt.pk]), follow=True)
        self.assertRedirects(foreign_challan_response, reverse("godown-stock-history"))
        self.assertNotContains(foreign_challan_response, "FOREIGN-CHALLAN-SECRET")
        self.assertNotContains(foreign_challan_response, self.other_product.name)
        self.assertContains(foreign_challan_response, self.other_group.name)

        # Accessing another group's product history from the wrong group does not leak data
        foreign_product_response = self.client.get(reverse("godown-stock-history-product", args=[self.other_product.pk]), follow=True)
        self.assertRedirects(foreign_product_response, reverse("godown-stock-history"))
        self.assertNotContains(foreign_product_response, "FOREIGN-CHALLAN-SECRET")
        self.assertContains(foreign_product_response, self.other_group.name)

        # 3. A missing product or invalid challan ID produces a graceful response instead of a DEBUG traceback
        missing_product_response = self.client.get(reverse("godown-stock-history-product", args=[999999]), follow=True)
        self.assertRedirects(missing_product_response, reverse("godown-stock-history"))
        self.assertContains(missing_product_response, "not found")

        missing_challan_response = self.client.get(reverse("godown-stock-history-challan", args=[999999]), follow=True)
        self.assertRedirects(missing_challan_response, reverse("godown-stock-history"))
        self.assertContains(missing_challan_response, "not found")

        # 4. Opening history and challan pages does not change stock quantities or create duplicate stock transactions
        initial_receipt_count = GodownStockReceipt.objects.count()
        self.client.get(reverse("godown-stock-history"))
        self.client.get(reverse("godown-stock-history-product", args=[self.product_one.pk]))
        self.client.get(reverse("godown-stock-history-challan", args=[receipt.pk]))
        self.assertEqual(GodownStockReceipt.objects.count(), initial_receipt_count)

    def test_bulk_entry_rejects_submission_with_only_empty_rows(self):
        token = self.submission_token()
        data = {
            "submission_token": token,
            "received_at": "2026-10-20T12:00",
            "reference": "CH-ALL-EMPTY",
            "notes": "Testing all empty",
            "receipts-TOTAL_FORMS": "2",
            "receipts-INITIAL_FORMS": "0",
            "receipts-MIN_NUM_FORMS": "0",
            "receipts-MAX_NUM_FORMS": "1000",
            "receipts-0-product": "",
            "receipts-0-received_ctn": "0",
            "receipts-0-received_pcs": "0",
            "receipts-1-product": "",
            "receipts-1-received_ctn": "",
            "receipts-1-received_pcs": "",
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please add at least one product with a valid quantity.")
        self.assertFalse(GodownStockReceipt.objects.filter(group=self.group).exists())

