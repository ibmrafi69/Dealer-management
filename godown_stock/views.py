from uuid import uuid4

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Min, Q, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from products.models import Category, Product
from dealers.context import get_current_group

from .forms import (
    BulkStockReceiptDetailsForm,
    BulkStockReceiptFormSet,
    active_products_for_group,
)
from .models import GodownStockReceipt
from .services import stock_rows


SUBMISSION_TOKENS_SESSION_KEY = "godown_stock_submission_tokens"
COMPLETED_TOKENS_SESSION_KEY = "completed_godown_stock_submission_tokens"


def _issue_submission_token(request):
    tokens = list(request.session.get(SUBMISSION_TOKENS_SESSION_KEY, []))[-19:]
    token = uuid4().hex
    tokens.append(token)
    request.session[SUBMISSION_TOKENS_SESSION_KEY] = tokens
    return token


def _complete_submission_token(request, token):
    request.session[SUBMISSION_TOKENS_SESSION_KEY] = [
        candidate for candidate in request.session.get(SUBMISSION_TOKENS_SESSION_KEY, []) if candidate != token
    ]
    completed = list(request.session.get(COMPLETED_TOKENS_SESSION_KEY, []))[-19:]
    completed.append(token)
    request.session[COMPLETED_TOKENS_SESSION_KEY] = completed


def _category_sorted(products):
    category_order = {category_id: index for index, category_id in enumerate(Category.objects.filter(group=products[0].group_id).values_list("id", flat=True))} if products else {}
    return sorted(products, key=lambda product: (category_order.get(product.category_id, len(category_order)), product.name.lower()))


def godown_stock(request):
    group = get_current_group(request)
    query = request.GET.get("q", "").strip()
    category_filter = request.GET.get("category", "").strip()
    products = Product.objects.filter(group=group, active=True)
    if query:
        products = products.filter(Q(name__icontains=query) | Q(category__name__icontains=query))
    if category_filter:
        products = products.filter(category__name__iexact=category_filter)
    products = _category_sorted(products)
    rows_by_product = {row["product"].pk: row for row in stock_rows(products)}
    grouped_rows = []
    for category in Category.objects.filter(group=group, active=True):
        category_rows = [rows_by_product[product.pk] for product in products if product.category_id == category.id]
        if category_rows:
            grouped_rows.append((category, category_rows))
    return render(
        request,
        "godown_stock/stock_list.html",
        {
            "grouped_rows": grouped_rows,
            "categories": Category.objects.filter(group=group, active=True),
            "query": query,
            "category_filter": category_filter,
        },
    )


def add_stock(request):
    group = get_current_group(request)
    details_form = BulkStockReceiptDetailsForm(request.POST or None)
    formset = BulkStockReceiptFormSet(request.POST or None, form_kwargs={"group": group}, prefix="receipts")
    submission_token = request.POST.get("submission_token", "") if request.method == "POST" else _issue_submission_token(request)

    if request.method == "POST":
        completed_tokens = request.session.get(COMPLETED_TOKENS_SESSION_KEY, [])
        issued_tokens = request.session.get(SUBMISSION_TOKENS_SESSION_KEY, [])
        if submission_token in completed_tokens:
            messages.warning(request, "This stock entry was already saved.")
            return redirect("godown-stock")
        if submission_token not in issued_tokens:
            details_form.add_error(None, "This form has expired. Please submit the new form below.")
            submission_token = _issue_submission_token(request)
        elif details_form.is_valid() and formset.is_valid():
            details = details_form.cleaned_data
            with transaction.atomic():
                receipts = []
                for row_form in formset:
                    if getattr(row_form, "is_empty_row", False):
                        continue
                    row = row_form.cleaned_data
                    product = row.get("product")
                    if not product:
                        continue
                    receipt = GodownStockReceipt(
                        group=group,
                        product=product,
                        received_at=details["received_at"],
                        received_ctn=row.get("received_ctn", 0) or 0,
                        received_pcs=row.get("received_pcs", 0) or 0,
                        reference=details["reference"],
                        notes=details["notes"],
                    )
                    receipt.save()
                    receipts.append(receipt)
            _complete_submission_token(request, submission_token)
            messages.success(request, f"Saved {len(receipts)} stock receipt{'s' if len(receipts) != 1 else ''}.")
            return redirect("godown-stock")

    products = active_products_for_group(group)
    return render(
        request,
        "godown_stock/add_stock.html",
        {
            "details_form": details_form,
            "formset": formset,
            "submission_token": submission_token,
            "product_ctn_sizes": {product.pk: product.ctn_size for product in products},
        },
    )


def stock_history_view(request, product_id=None):
    group = get_current_group(request)
    product = None
    receipts = GodownStockReceipt.objects.filter(group=group).exclude(reference="")
    if product_id:
        product = Product.objects.filter(pk=product_id).select_related("group").first()
        if not product:
            receipt = GodownStockReceipt.objects.filter(pk=product_id).select_related("group").first()
            if receipt:
                if receipt.group_id == group.id:
                    return redirect("godown-stock-history-challan", receipt_id=receipt.pk)
                messages.warning(
                    request,
                    f"This stock challan belongs to group '{receipt.group.name}'. Please switch to '{receipt.group.name}' to view it.",
                )
                return redirect("godown-stock-history")
            messages.warning(request, "The requested stock history or product was not found.")
            return redirect("godown-stock-history")

        if product.group_id != group.id:
            messages.warning(
                request,
                f"'{product.name}' belongs to group '{product.group.name}'. Please switch to '{product.group.name}' to view its stock history.",
            )
            return redirect("godown-stock-history")

        receipts = receipts.filter(product=product)

    challans = (
        receipts.annotate(entry_date=TruncDate("received_at"))
        .values("entry_date", "reference")
        .annotate(
            product_count=Count("product_id", distinct=True),
            total_pieces=Sum("total_pieces"),
            first_receipt_id=Min("pk"),
        )
        .order_by("-entry_date", "-first_receipt_id")
    )
    return render(
        request,
        "godown_stock/stock_history.html",
        {
            "product": product,
            "challans": challans,
        },
    )


def challan_history_detail_view(request, receipt_id):
    group = get_current_group(request)
    challan_receipt = (
        GodownStockReceipt.objects.exclude(reference="")
        .select_related("product", "group")
        .filter(pk=receipt_id)
        .first()
    )
    if not challan_receipt:
        messages.warning(request, "The requested stock challan was not found.")
        return redirect("godown-stock-history")

    if challan_receipt.group_id != group.id:
        messages.warning(
            request,
            f"This stock challan belongs to group '{challan_receipt.group.name}'. Please switch to '{challan_receipt.group.name}' to view it.",
        )
        return redirect("godown-stock-history")

    entry_date = timezone.localtime(challan_receipt.received_at).date()
    receipts = list(
        GodownStockReceipt.objects.filter(
            group=group,
            reference=challan_receipt.reference,
            received_at__date=entry_date,
        )
        .select_related("product")
        .order_by("created_at", "pk")
    )
    total_pieces = sum((receipt.total_pieces for receipt in receipts), 0)
    return render(
        request,
        "godown_stock/challan_history_detail.html",
        {
            "challan": challan_receipt.reference,
            "entry_date": entry_date,
            "receipts": receipts,
            "product_count": len({receipt.product_id_snapshot or receipt.product_id for receipt in receipts}),
            "total_pieces": total_pieces,
        },
    )
