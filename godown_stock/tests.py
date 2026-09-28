from datetime import date
from decimal import Decimal

from django.test import TestCase

from products.models import Product
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
            order_quantity=Decimal("1.25"),  # 1.25 CTN x 24 = 30 PCS
        )
        pending = SalesTransaction.objects.create(
            date=date(2026, 9, 28),
            invoice_number="GODOWN-PENDING",
            status=SalesTransaction.Status.PENDING,
        )
        SalesItem.objects.create(transaction=pending, product=self.product, order_quantity=Decimal("1.00"))

        self.assertEqual(self.balance_for_product(), Decimal("18"))
        self.assertEqual(stock_display(self.balance_for_product(), self.product.ctn_size), "0 CTN 18 PCS")

        item.return_quantity = Decimal("0.42")  # 0.42 CTN x 24 = 10.08 PCS
        item.save()

        self.assertEqual(self.balance_for_product(), Decimal("28.08"))
        movements = [event["movement"] for event in stock_history(self.product)]
        self.assertIn("Finalized dispatch", movements)
        self.assertIn("Finalized return", movements)
        self.assertNotIn("GODOWN-PENDING", [event["reference"] for event in stock_history(self.product)])
