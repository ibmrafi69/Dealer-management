from datetime import date
from decimal import Decimal

from sales.models import SalesTransaction

from .models import DealerCredit, DealerPayment

ZERO = Decimal("0")


def dealer_ledger(dealer, start_date=None, end_date=None):
    transactions = SalesTransaction.objects.filter(
        group=dealer.group,
        dealer=dealer,
        status=SalesTransaction.Status.FINALIZED,
    ).select_related("reconciliation").order_by("date", "created_at", "pk")
    payments = DealerPayment.objects.filter(group=dealer.group, dealer=dealer).order_by("payment_date", "created_at", "pk")
    manual_credits = DealerCredit.objects.filter(group=dealer.group, dealer=dealer).order_by("credit_date", "created_at", "pk")
    if start_date:
        transactions = transactions.filter(date__gte=start_date)
        payments = payments.filter(payment_date__gte=start_date)
        manual_credits = manual_credits.filter(credit_date__gte=start_date)
    if end_date:
        transactions = transactions.filter(date__lte=end_date)
        payments = payments.filter(payment_date__lte=end_date)
        manual_credits = manual_credits.filter(credit_date__lte=end_date)

    events = []
    if not start_date:
        events.append({
            "date": None,
            "type": "Opening Due",
            "reference": "Opening balance",
            "debit": Decimal(dealer.opening_due or 0),
            "credit": ZERO,
        })
    for transaction in transactions:
        reconciliation = getattr(transaction, "reconciliation", None)
        credit_amount = reconciliation.credit if reconciliation else transaction.grand_total_sale
        events.append({
            "date": transaction.date,
            "type": "Invoice",
            "reference": transaction.invoice_number,
            "debit": Decimal(credit_amount or 0),
            "credit": ZERO,
            "transaction": transaction,
        })
        return_amount = Decimal(transaction.return_total or 0)
        if return_amount:
            events.append({
                "date": transaction.date,
                "type": "Return",
                "reference": transaction.invoice_number,
                "debit": ZERO,
                "credit": return_amount,
                "transaction": transaction,
            })
        adjustment_amount = Decimal(reconciliation.discount or 0) if reconciliation else ZERO
        if adjustment_amount:
            events.append({
                "date": transaction.date,
                "type": "Adjustment",
                "reference": transaction.invoice_number,
                "debit": ZERO,
                "credit": adjustment_amount,
                "transaction": transaction,
            })
    for payment in payments:
        events.append({
            "date": payment.payment_date,
            "type": "Payment",
            "reference": payment.reference or f"PAY-{payment.pk:04d}",
            "debit": ZERO,
            "credit": Decimal(payment.amount),
            "payment": payment,
        })
    for credit in manual_credits:
        events.append({
            "date": credit.credit_date,
            "type": "Manual Credit",
            "reference": credit.reference or "Manual credit",
            "debit": Decimal(credit.amount),
            "credit": ZERO,
            "manual_credit": credit,
        })
    def event_sort_key(event):
        created_at = getattr(event.get("transaction"), "created_at", None) or getattr(event.get("payment"), "created_at", None) or getattr(event.get("manual_credit"), "created_at", None)
        return (event["date"] or date.min, created_at.timestamp() if created_at else 0, event["type"])

    events.sort(key=event_sort_key)
    balance = ZERO
    for event in events:
        balance += event["debit"] - event["credit"]
        event["balance"] = balance.quantize(Decimal("0.01"))
    return events


def dealer_due(dealer):
    ledger = dealer_ledger(dealer)
    return max((ledger[-1]["balance"] if ledger else ZERO), ZERO)


def dealer_aging(dealer, today=None):
    today = today or date.today()
    buckets = {"0-7 Days": ZERO, "8-30 Days": ZERO, "31-60 Days": ZERO, "60+ Days": ZERO}
    invoices = [event for event in dealer_ledger(dealer) if event["type"] in {"Invoice", "Manual Credit"} and event["debit"] > 0]
    reductions = sum((event["credit"] for event in dealer_ledger(dealer) if event["type"] in {"Payment", "Return", "Adjustment"}), ZERO)
    for invoice in invoices:
        outstanding = max(invoice["debit"] - reductions, ZERO)
        reductions = max(reductions - invoice["debit"], ZERO)
        age = max((today - invoice["date"]).days, 0)
        bucket = "0-7 Days" if age <= 7 else "8-30 Days" if age <= 30 else "31-60 Days" if age <= 60 else "60+ Days"
        buckets[bucket] += outstanding
    return buckets
