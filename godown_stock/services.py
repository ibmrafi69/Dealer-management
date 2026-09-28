from collections import defaultdict
from datetime import datetime, time
from decimal import Decimal

from django.utils import timezone

from sales.models import SalesItem, SalesTransaction

from .models import GodownStockReceipt


ZERO = Decimal("0")


def _piece_quantity(quantity, pieces_per_ctn):
    return Decimal(quantity or 0) * Decimal(pieces_per_ctn or 1)


def _display_number(value):
    value = Decimal(value or 0)
    if value == value.to_integral_value():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def stock_display(total_pieces, pieces_per_ctn):
    """Convert the source-of-truth total pieces into the requested CTN + PCS display."""
    total_pieces = Decimal(total_pieces or 0)
    per_ctn = Decimal(pieces_per_ctn or 1)
    prefix = ""
    if total_pieces < 0:
        prefix = "Short "
        total_pieces = abs(total_pieces)
    cartons, pieces = divmod(total_pieces, per_ctn)
    return f"{prefix}{_display_number(cartons)} CTN {_display_number(pieces)} PCS"


def _finalized_items(product_ids):
    return (
        SalesItem.objects.filter(
            product_id__in=product_ids,
            transaction__status=SalesTransaction.Status.FINALIZED,
        )
        .select_related("product", "transaction", "transaction__route", "transaction__dealer")
        .order_by("transaction__date", "transaction__created_at", "pk")
    )


def stock_rows(products):
    """Return calculated balances. Receipts and finalized invoices remain the only sources of truth."""
    product_ids = [product.pk for product in products]
    balances = defaultdict(lambda: ZERO)
    if not product_ids:
        return []

    for receipt in GodownStockReceipt.objects.filter(product_id__in=product_ids):
        balances[receipt.product_id] += Decimal(receipt.total_pieces)

    for item in _finalized_items(product_ids):
        pieces_per_ctn = item.ctn_size_snapshot or item.product.ctn_size
        # order_quantity is the dispatched quantity. A return adds usable stock
        # back. SalesItem already treats damage as part of that dispatch
        # (sale = order - return - damage), so subtracting damage again would
        # double-count the loss after invoice edits.
        balances[item.product_id] -= _piece_quantity(item.order_quantity, pieces_per_ctn)
        balances[item.product_id] += _piece_quantity(item.return_quantity, pieces_per_ctn)

    rows = []
    for product in products:
        balance = balances[product.pk]
        rows.append(
            {
                "product": product,
                "balance_pieces": balance,
                "current_stock": stock_display(balance, product.ctn_size),
                "status": "In stock" if balance > 0 else "Out of stock" if balance == 0 else "Stock deficit",
            }
        )
    return rows


def _invoice_datetime(item):
    transaction = item.transaction
    transaction_time = timezone.localtime(transaction.created_at).time() if transaction.created_at else time.min
    value = datetime.combine(transaction.date, transaction_time)
    return timezone.make_aware(value) if timezone.is_naive(value) else value


def stock_history(product):
    """Build a readable ledger from stored receipts and finalized invoice data."""
    events = []
    for receipt in GodownStockReceipt.objects.filter(product=product).order_by("received_at", "created_at", "pk"):
        events.append(
            {
                "occurred_at": receipt.received_at,
                "order": (0, receipt.pk),
                "movement": "Received",
                "in_pieces": Decimal(receipt.total_pieces),
                "out_pieces": ZERO,
                "reference": receipt.reference or "Stock receipt",
                "notes": receipt.notes,
            }
        )

    for item in _finalized_items([product.pk]):
        pieces_per_ctn = item.ctn_size_snapshot or product.ctn_size
        dispatch = _piece_quantity(item.order_quantity, pieces_per_ctn)
        returned = _piece_quantity(item.return_quantity, pieces_per_ctn)
        damage = _piece_quantity(item.damage_quantity, pieces_per_ctn)
        occurred_at = _invoice_datetime(item)
        reference = item.transaction.invoice_number
        if dispatch:
            events.append(
                {
                    "occurred_at": occurred_at,
                    "order": (1, item.pk),
                    "movement": "Finalized dispatch",
                    "in_pieces": ZERO,
                    "out_pieces": dispatch,
                    "reference": reference,
                    "notes": "Finalized Daily Sales invoice",
                }
            )
        if returned:
            events.append(
                {
                    "occurred_at": occurred_at,
                    "order": (2, item.pk),
                    "movement": "Finalized return",
                    "in_pieces": returned,
                    "out_pieces": ZERO,
                    "reference": reference,
                    "notes": "Return recorded on the finalized invoice",
                }
            )
        if damage:
            events.append(
                {
                    "occurred_at": occurred_at,
                    "order": (3, item.pk),
                    "movement": "Damage",
                    "in_pieces": ZERO,
                    "out_pieces": ZERO,
                    "reference": reference,
                    "notes": f"{_display_number(damage)} PCS damaged; already included in that invoice's dispatched quantity.",
                }
            )

    events.sort(key=lambda event: (event["occurred_at"], event["order"]))
    balance = ZERO
    for event in events:
        balance += event["in_pieces"] - event["out_pieces"]
        event["balance_pieces"] = balance
        event["in_display"] = _display_number(event["in_pieces"]) if event["in_pieces"] else "-"
        event["out_display"] = _display_number(event["out_pieces"]) if event["out_pieces"] else "-"
        event["balance_display"] = stock_display(balance, product.ctn_size)
    return events
