from calendar import month_name
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import logging

from django.db import IntegrityError
from django.db.models import Count
from django.db import transaction as db_transaction
from django.http import JsonResponse
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render

from dealers.context import get_current_group
from dealers.models import Dealer, Route
from godown_stock.services import stock_balances, stock_display
from inventory.models import StockTransaction
from products.models import Product

from .models import CURRENCY_DENOMINATIONS, CurrencyCount

from .models import PaymentReconciliation, SalesItem, SalesTransaction


logger = logging.getLogger(__name__)


class StockShortageWarning(Exception):
    def __init__(self, warnings):
        self.warnings = warnings
        super().__init__("; ".join(warnings))


def currency_count_context(currency_count=None, form_data=None):
    rows = []
    for denomination in CURRENCY_DENOMINATIONS:
        count = currency_count.quantity_for(denomination) if currency_count else 0
        if form_data is not None:
            try:
                count = int(form_data.get(f"currency_count_{denomination}", count) or 0)
            except (TypeError, ValueError):
                count = 0
        rows.append((denomination, count, Decimal(denomination) * count))
    return {
        "currency_denominations": rows,
        "currency_total_cash": sum((row[2] for row in rows), Decimal("0")),
        "has_currency_count": currency_count is not None,
    }


def update_currency_count_from_request(request, currency_count):
    """Validate and save whole-note counts; the result is the cash source of truth."""
    for denomination in CURRENCY_DENOMINATIONS:
        raw_quantity = request.POST.get(f"currency_count_{denomination}", "0")
        try:
            quantity = int(raw_quantity or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("Currency quantities must be whole non-negative numbers.") from exc
        if quantity < 0:
            raise ValueError("Currency quantities cannot be negative.")
        setattr(currency_count, CurrencyCount.quantity_field(denomination), quantity)
    currency_count.save()
    return currency_count

def _stock_warnings(requirements):
    requested_pieces = {}
    products_by_id = {}
    for product, quantity in requirements:
        try:
            quantity = Decimal(str(quantity or 0))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("Enter a valid Daily Sales quantity.") from exc
        if quantity < 0:
            raise ValueError("Daily Sales quantity cannot be negative.")
        products_by_id[product.pk] = product
        requested_pieces[product.pk] = requested_pieces.get(product.pk, Decimal("0")) + quantity

    balances = stock_balances(list(products_by_id.values()))
    warnings = []
    for product_id, requested in requested_pieces.items():
        # A selected zero-quantity line does not dispatch anything, so it must
        # not be rejected merely because this product is currently out of stock.
        if requested == 0:
            continue
        product = products_by_id[product_id]
        available = balances.get(product_id, Decimal("0"))
        if requested > available:
            warnings.append(
                f"{product.name} - Ordered {requested} {product.unit}, Available {available} {product.unit}."
            )
    return warnings


def _validate_stock_requirements(requirements, confirm_short_stock):
    warnings = _stock_warnings(requirements)
    if warnings and confirm_short_stock != "1":
        raise StockShortageWarning(warnings)


def _stock_confirmation_signature(values):
    payload = "|".join(f"{product_id}:{quantity}" for product_id, quantity in values)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_edit_stock_requirements(transaction, items, confirm_short_stock):
    requested = {}
    existing = {}
    products = {}
    for item in items:
        try:
            quantity = Decimal(str(item.order_quantity or 0))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("Enter a valid Daily Sales quantity.") from exc
        if quantity < 0:
            raise ValueError("Daily Sales quantity cannot be negative.")
        products[item.product_id] = item.product
        requested[item.product_id] = requested.get(item.product_id, Decimal("0")) + quantity
        existing[item.product_id] = existing.get(item.product_id, Decimal("0")) + quantity
    balances = stock_balances(list(products.values()))
    warnings = []
    for product_id, quantity in requested.items():
        available = balances.get(product_id, Decimal("0"))
        if transaction.status == SalesTransaction.Status.FINALIZED:
            available += existing.get(product_id, Decimal("0"))
        if quantity > available:
            warnings.append(f"{products[product_id].name} - Ordered {quantity} {products[product_id].unit}, Available {available} {products[product_id].unit}.")
    if warnings and confirm_short_stock != "1":
        raise StockShortageWarning(warnings)


def _apply_edit_form_data(transaction, form_data):
    transaction.notes = form_data.get("notes", transaction.notes)
    reconciliation = getattr(transaction, "reconciliation", None)
    if reconciliation:
        for field in ("cash", "expenses", "credit", "discount", "others"):
            value = form_data.get(field if field != "discount" else "discount", None)
            if value is not None:
                setattr(reconciliation, field, Decimal(value or 0))
    for item in transaction.items.all():
        for field in ("order_quantity", "return_quantity", "foc_quantity", "free_product_quantity", "damage_quantity", "discount"):
            value = form_data.get(f"{field}_{item.pk}")
            if value is not None:
                setattr(item, field, Decimal(value or 0))
        for field, form_field in (("dealer_price_snapshot", "dealer_price"), ("trade_price_snapshot", "trade_price"), ("foc_snapshot", "foc_price"), ("sale_price_snapshot", "sale_price")):
            value = form_data.get(f"{form_field}_{item.pk}")
            if value is not None:
                setattr(item, field, Decimal(value or 0))


def sales_entry(request):
    group = get_current_group(request)
    routes = list(Route.objects.filter(group=group, active=True))
    weekday_order = {weekday: index for index, weekday in enumerate(Route.WEEKDAY_ORDER)}
    routes.sort(key=lambda route: (weekday_order.get(route.weekday, len(weekday_order)), route.route_name.lower()))
    all_products = list(Product.objects.filter(group=group, active=True))
    category_order = {category_id: index for index, category_id in enumerate(group.categories.values_list("id", flat=True))}
    all_products.sort(key=lambda product: (category_order.get(product.category_id, len(category_order)), product.name.lower()))
    balances = stock_balances(all_products)
    # Pending invoices are deliberately not reservations. Keep every active
    # Product Setup item selectable; validation happens only when the user
    # finalizes the invoice, after all of its product lines are considered.
    products = all_products
    for product in all_products:
        available = balances.get(product.pk, Decimal("0"))
        product.available_stock_pieces = available
        product.available_stock_display = stock_display(available, product.ctn_size, product.unit)
    product_groups = [(category.name, [product for product in products if product.category_id == category.id]) for category in group.categories.filter(active=True)]
    selected_date = request.POST.get("date") if request.method == "POST" else request.GET.get("date")
    try:
        selected_date = date.fromisoformat(selected_date) if selected_date else date.today()
    except ValueError:
        selected_date = date.today()
    selected_day = selected_date.strftime("%A")
    weekday_by_date_index = (Route.MONDAY, Route.TUESDAY, Route.WEDNESDAY, Route.THURSDAY, None, Route.SATURDAY, Route.SUNDAY)
    expected_weekday = weekday_by_date_index[selected_date.weekday()]
    default_route_name = Route.DEFAULT_ROUTE_BY_WEEKDAY.get(expected_weekday)
    for route in routes:
        route.is_default_route = route.route_name.casefold() == (Route.DEFAULT_ROUTE_BY_WEEKDAY.get(route.weekday) or "").casefold()
    default_route = next(
        (route for route in routes if route.route_name.casefold() == (default_route_name or "").casefold()),
        None,
    )
    route_suggestions = [(route.weekday, route.route_name) for route in routes if route.is_default_route]
    error = None
    stock_warnings = []
    stock_confirmation_signature = ""
    product_ids = request.POST.getlist("product_id") if request.method == "POST" else []
    order_quantities = request.POST.getlist("order_quantity") if request.method == "POST" else []
    return_quantities = request.POST.getlist("return_quantity") if request.method == "POST" else []
    foc_quantities = request.POST.getlist("foc_quantity") if request.method == "POST" else []
    free_product_quantities = request.POST.getlist("free_product_quantity") if request.method == "POST" else []
    discounts = request.POST.getlist("discount") if request.method == "POST" else []
    damage_quantities = request.POST.getlist("damage_quantity") if request.method == "POST" else []

    def row_value(values, index):
        return values[index] if index < len(values) else ""

    selected_items = []
    if request.method == "POST":
        for index, product_id in enumerate(product_ids):
            if not product_id:
                continue
            try:
                product = Product.objects.get(pk=product_id, group=group, active=True)
            except (Product.DoesNotExist, ValueError) as exc:
                error = "Select an active product from Product Setup."
                break
            selected_items.append((index, product))

    if request.method == "POST":
        try:
            save_action = request.POST.get("save_action", "finalize")
            if save_action not in {"pending", "finalize"}:
                raise ValueError("Unknown save action.")
            with db_transaction.atomic():
                if save_action == "finalize":
                    _validate_stock_requirements(
                        [(product, row_value(order_quantities, index)) for index, product in selected_items],
                        request.POST.get("confirm_short_stock") if request.POST.get("stock_confirmation_signature") == _stock_confirmation_signature(zip(product_ids, order_quantities)) else None,
                    )
                route_name = request.POST.get("route_name", "").strip()
                route = Route.objects.filter(group=group, route_name__iexact=route_name, active=True).first()
                dealer_id = request.POST.get("dealer") or None
                dealer = Dealer.objects.filter(pk=dealer_id, group=group).first() if dealer_id else None
                if not route_name and not request.POST.get("dealer"):
                    raise ValueError("Select or enter a route.")
                if dealer_id and dealer is None:
                    raise ValueError("Select a dealer from the current group.")
                if dealer:
                    if not dealer.route_id:
                        raise ValueError("The selected dealer must belong to a route.")
                    route = dealer.route
                    route_name = route.route_name
                if route_name and not route:
                    route = Route(
                        group=group,
                        route_name=route_name,
                        weekday=expected_weekday or Route.SATURDAY,
                    )
                    route.full_clean()
                    route.save()
                transaction_date = date.fromisoformat(request.POST["date"])
                legacy_invoice_number = request.POST.get("invoice_number", "").strip() if not route_name and request.POST.get("dealer") else ""
                sale = None
                for attempt in range(5):
                    try:
                        with db_transaction.atomic():
                            sale = SalesTransaction.objects.create(
                                group=group,
                                route=route,
                                route_day=route.weekday if route else "",
                                status=SalesTransaction.Status.PENDING if save_action == "pending" else SalesTransaction.Status.FINALIZED,
                                dealer=dealer,
                                date=transaction_date,
                                invoice_number=legacy_invoice_number,
                                notes=request.POST.get("notes", "").strip(),
                            )
                        break
                    except IntegrityError:
                        if legacy_invoice_number or attempt == 4:
                            raise
                for index, product in selected_items:
                    item = SalesItem.objects.create(
                        transaction=sale,
                        product=product,
                        order_quantity=row_value(order_quantities, index) or 0,
                        return_quantity=row_value(return_quantities, index) or 0,
                        foc_quantity=row_value(foc_quantities, index) or 0,
                        free_product_quantity=row_value(free_product_quantities, index) or 0,
                        damage_quantity=row_value(damage_quantities, index) or 0,
                        discount=row_value(discounts, index) or 0,
                    )
                    damage_quantity = Decimal(row_value(damage_quantities, index) or 0)
                    if damage_quantity > 0:
                        from inventory.models import Damage

                        damage = Damage.objects.create(
                            date=sale.date,
                            product=item.product,
                            quantity=damage_quantity,
                            related_transaction=sale,
                            reason="Recorded during daily sales entry",
                        )
                        StockTransaction.record_damage(damage)
                    StockTransaction.record_sale_item(item)
                    StockTransaction.record_return_item(item)

                currency_count = update_currency_count_from_request(request, CurrencyCount(transaction=sale))
                PaymentReconciliation.objects.create(
                    transaction=sale,
                    cash=request.POST.get("cash") or 0,
                    expenses=request.POST.get("expenses") or 0,
                    credit=request.POST.get("credit") or 0,
                    discount=request.POST.get("payment_discount") or 0,
                    others=request.POST.get("others") or 0,
                )
                reconciliation = PaymentReconciliation.objects.get(transaction=sale)
                reconciliation.cash = currency_count.total_cash
                reconciliation.save()
                if save_action == "pending":
                    return redirect(f"{reverse('pending-sales')}?date={sale.date.isoformat()}")
                return redirect("daily-summary-date", sale.date.isoformat())
        except StockShortageWarning as exc:
            stock_warnings = exc.warnings
            stock_confirmation_signature = _stock_confirmation_signature(zip(product_ids, order_quantities))
            error = "Stock warning: confirm the quantities below to save anyway."
        except Exception as exc:
            logger.exception("Daily Sales save failed")
            error = str(exc)

    form_rows = []
    if request.method == "POST":
        for index in range(len(product_ids)):
            form_rows.append({
                "product_id": row_value(product_ids, index),
                "order_quantity": row_value(order_quantities, index),
                "return_quantity": row_value(return_quantities, index),
                "foc_quantity": row_value(foc_quantities, index),
                "free_product_quantity": row_value(free_product_quantities, index),
                "discount": row_value(discounts, index),
                "damage_quantity": row_value(damage_quantities, index),
            })
    if not form_rows:
        form_rows = [{
            "product_id": "",
            "order_quantity": "0",
            "return_quantity": "0",
            "foc_quantity": "0",
            "free_product_quantity": "0",
            "discount": "0",
            "damage_quantity": "0",
        }]
    # Keep the route-day choices explicit in the form context. The template
    # renders this list directly, so relying on a broad locals() context makes
    # an empty dropdown too easy to reintroduce during future view changes.
    context = {
        "routes": routes,
        "dealers": Dealer.objects.filter(group=group, active=True).select_related("route").order_by("name"),
        "selected_dealer_id": request.POST.get("dealer", "") if request.method == "POST" else request.GET.get("dealer", ""),
        "products": products,
        "product_groups": product_groups,
        "today": selected_date,
        "selected_day": selected_day,
        "preview_invoice_number": SalesTransaction.next_invoice_number(selected_date),
        "route_name_value": request.POST.get("route_name", "").strip() if request.method == "POST" else (default_route.route_name if default_route else ""),
        "default_route": default_route,
        "route_suggestions": route_suggestions,
        "weekdays": Route.WEEKDAY_CHOICES,
        "pending_count": SalesTransaction.objects.filter(group=group, status=SalesTransaction.Status.PENDING, date=selected_date).count(),
        "error": error,
        "stock_warnings": stock_warnings,
        "stock_confirmation_signature": stock_confirmation_signature,
        "form_rows": form_rows,
    }
    context.update(
        currency_count_context(
            form_data=request.POST if request.method == "POST" else None,
        )
    )
    return render(request, "sales/entry.html", context)


def pending_sales(request):
    group = get_current_group(request)
    try:
        selected_date = date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        selected_date = date.today()
    pending_transactions = (
        SalesTransaction.objects.filter(group=group, status=SalesTransaction.Status.PENDING, date=selected_date)
        .select_related("route", "dealer")
        .annotate(item_count=Count("items"))
        .order_by("-updated_at", "-created_at")
    )
    return render(
        request,
        "sales/pending_list.html",
        {
            "pending_transactions": pending_transactions,
            "selected_date": selected_date,
        },
    )


def invoice_preview(request):
    try:
        selected_date = date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        selected_date = date.today()
    return JsonResponse({"invoice_number": SalesTransaction.next_invoice_number(selected_date)})


def _finalized_summary_transactions(group, selected_date, selected_year, selected_month, route_id):
    filters = {"group": group, "status": SalesTransaction.Status.FINALIZED}
    if selected_date:
        filters["date"] = selected_date
    else:
        filters.update(date__year=selected_year, date__month=selected_month)
    transactions = (
        SalesTransaction.objects.filter(**filters)
        .select_related("dealer", "route")
        .prefetch_related("items__product", "damages", "reconciliation")
        .order_by("-date", "-created_at", "-pk")
    )
    if route_id:
        transactions = transactions.filter(route_id=route_id)
    return transactions


def daily_summary(request, report_date=None):
    group = get_current_group(request)
    today = date.today()
    date_filter = report_date or request.GET.get("date")
    try:
        selected_date = date.fromisoformat(date_filter) if date_filter else None
    except ValueError:
        selected_date = None
    default_year = selected_date.year if selected_date else today.year
    default_month = selected_date.month if selected_date else today.month
    try:
        selected_year = int(request.GET.get("year", default_year))
        selected_month = int(request.GET.get("month", default_month))
    except ValueError:
        selected_year, selected_month = default_year, default_month
    if not (1 <= selected_year <= 9999 and 1 <= selected_month <= 12):
        selected_year, selected_month = default_year, default_month
    route_id = request.GET.get("route", "")
    transactions = _finalized_summary_transactions(group, selected_date, selected_year, selected_month, route_id)
    totals = {
        "orders": transactions.values("invoice_number").distinct().count(),
        "order": sum((sale.order_total for sale in transactions), Decimal("0")),
        "sales": sum((sale.sale_total for sale in transactions), Decimal("0")),
        "returns": sum((sale.return_total for sale in transactions), Decimal("0")),
        "damage": sum((sale.damage_total for sale in transactions), Decimal("0")),
        "discount": sum((sale.total_discount for sale in transactions), Decimal("0")),
        "free_product": sum((sale.free_product_total for sale in transactions), Decimal("0")),
        "grand_total": sum((sale.grand_total_sale for sale in transactions), Decimal("0")),
        "net": sum((sale.net_sale for sale in transactions), Decimal("0")),
        "cash": sum((getattr(getattr(sale, "reconciliation", None), "cash", Decimal("0")) for sale in transactions), Decimal("0")),
        "expenses": sum((getattr(getattr(sale, "reconciliation", None), "expenses", Decimal("0")) for sale in transactions), Decimal("0")),
        "credit": sum((getattr(getattr(sale, "reconciliation", None), "credit", Decimal("0")) for sale in transactions), Decimal("0")),
        "payment_discount": sum((getattr(getattr(sale, "reconciliation", None), "discount", Decimal("0")) for sale in transactions), Decimal("0")),
        "others": sum((getattr(getattr(sale, "reconciliation", None), "others", Decimal("0")) for sale in transactions), Decimal("0")),
        "shortage": sum((getattr(getattr(sale, "reconciliation", None), "shortage", sale.grand_total_sale) for sale in transactions), Decimal("0")),
        "order_qty": sum((sum((item.order_quantity for item in sale.items.all()), Decimal("0")) for sale in transactions), Decimal("0")),
        "return_qty": sum((sum((item.return_quantity for item in sale.items.all()), Decimal("0")) for sale in transactions), Decimal("0")),
        "damage_qty": sum((sum((damage.quantity for damage in sale.damages.all()), Decimal("0")) for sale in transactions), Decimal("0")),
    }
    daily_records = [
        {
            "id": sale.id,
            "date": sale.date,
            "invoice": sale.invoice_number,
            "route": sale.route_display,
            "status": sale.get_status_display(),
            "sent_quantity": sale.sent_quantity_total,
            "sent_pieces": sale.sent_pieces_total,
            "sale_quantity": sale.sale_quantity_total,
            "sale_pieces": sale.sale_pieces_total,
            "return_quantity": sale.return_quantity_total,
            "return_pieces": sale.return_pieces_total,
            "damage_quantity": sale.damage_quantity_total,
            "damage_pieces": sale.damage_pieces_total,
            "sales": sale.sale_total,
            "returns": sale.return_total,
            "damage": sale.damage_total,
            "discount": sale.total_discount,
            "shortage": getattr(getattr(sale, "reconciliation", None), "shortage", sale.grand_total_sale),
            "net": sale.net_sale,
        }
        for sale in transactions
    ]
    product_details = {}
    for sale in transactions:
        for item in sale.items.all():
            # Use the line snapshot, rather than the mutable Product Setup
            # record, so reports remain a faithful invoice history.
            key = (
                item.product_id_snapshot if item.product_id_snapshot is not None else item.product_id,
                item.product_name_snapshot or (item.product.name if item.product_id else ""),
                item.category_snapshot,
            )
            detail = product_details.setdefault(
                key,
                {
                    "name": key[1],
                    "category": key[2],
                    "sale": Decimal("0"),
                    "pieces": Decimal("0"),
                    "value": Decimal("0"),
                },
            )
            detail["sale"] += item.sale_quantity
            detail["pieces"] += item.sale_quantity
            detail["value"] += item.sale_value
    export_query = f"?year={selected_year}&month={selected_month}{('&route=' + route_id) if route_id else ''}"
    excel_export_url = f"/reports/daily/export/?date={selected_date}" if selected_date else f"/reports/monthly/export/{export_query}"
    pdf_export_url = f"/reports/monthly/export/pdf/{export_query}"
    return render(request, "sales/daily_summary.html", {"transactions": transactions, "daily_records": daily_records, "product_details": sorted(product_details.values(), key=lambda detail: (detail["category"], detail["name"].lower())), "totals": totals, "selected_date": selected_date, "selected_year": selected_year, "selected_month": selected_month, "selected_route_id": route_id, "routes": Route.objects.filter(group=group, active=True), "month_options": [(number, month_name[number]) for number in range(1, 13)], "excel_export_url": excel_export_url, "pdf_export_url": pdf_export_url, "period_label": selected_date.strftime("%d %B %Y") if selected_date else f"{month_name[selected_month]} {selected_year}"})


def sales_invoice_detail(request, pk):
    """Render a finalized invoice as report history, never as an edit form."""
    group = get_current_group(request)
    transaction = get_object_or_404(
        SalesTransaction.objects.filter(group=group, status=SalesTransaction.Status.FINALIZED)
        .select_related("route", "dealer", "reconciliation")
        .prefetch_related("items__product", "damages"),
        pk=pk,
    )
    currency_count = CurrencyCount.objects.filter(transaction=transaction).first()
    return render(
        request,
        "sales/invoice_detail.html",
        {
            "transaction": transaction,
            "reconciliation": getattr(transaction, "reconciliation", None),
            **currency_count_context(currency_count),
        },
    )


def sales_edit(request, pk):
    group = get_current_group(request)
    transaction = get_object_or_404(SalesTransaction.objects.filter(group=group).select_related("route").prefetch_related("items", "reconciliation"), pk=pk)
    template_name = "sales/pending_edit.html" if transaction.status == SalesTransaction.Status.PENDING else "sales/edit.html"
    stock_warnings = []
    stock_confirmation_signature = ""
    if request.method == "POST":
        try:
            with db_transaction.atomic():
                transaction = SalesTransaction.objects.select_for_update().get(pk=pk, group=group)
                save_action = request.POST.get("save_action", "pending" if transaction.status == SalesTransaction.Status.PENDING else "finalize")
                if request.POST.get("confirm_short_stock") == "1":
                    save_action = "finalize"
                if save_action not in {"pending", "finalize"}:
                    raise ValueError("Unknown save action.")
                items = list(transaction.items.select_related("product").all())
                for item in items:
                    item.order_quantity = request.POST.get(f"order_quantity_{item.pk}") or item.order_quantity
                if save_action == "finalize" or transaction.status == SalesTransaction.Status.FINALIZED:
                    confirmation = request.POST.get("confirm_short_stock") if request.POST.get("stock_confirmation_signature") == _stock_confirmation_signature((item.pk, item.order_quantity) for item in items) else None
                    _validate_edit_stock_requirements(transaction, items, confirmation)
                for item in items:
                    item.return_quantity = request.POST.get(f"return_quantity_{item.pk}") or item.return_quantity
                    # FOC quantity is retained for older invoices even though
                    # the sheet now presents the product's FOC price column.
                    item.foc_quantity = request.POST.get(f"foc_quantity_{item.pk}") or item.foc_quantity
                    item.free_product_quantity = request.POST.get(f"free_product_quantity_{item.pk}") or item.free_product_quantity
                    item.damage_quantity = request.POST.get(f"damage_quantity_{item.pk}") or item.damage_quantity
                    item.discount = request.POST.get(f"discount_{item.pk}") or item.discount
                    item.dealer_price_snapshot = request.POST.get(f"dealer_price_{item.pk}") or item.dealer_price_snapshot
                    item.trade_price_snapshot = request.POST.get(f"trade_price_{item.pk}") or item.trade_price_snapshot
                    item.foc_snapshot = request.POST.get(f"foc_price_{item.pk}") or item.foc_snapshot
                    item.sale_price_snapshot = request.POST.get(f"sale_price_{item.pk}") or item.sale_price_snapshot
                    item.save()
                    from inventory.models import Damage

                    damage = Damage.objects.filter(related_transaction=transaction, product=item.product).first()
                    if damage:
                        damage.quantity = item.damage_quantity
                        damage.save()
                    elif item.damage_quantity > 0:
                        Damage.objects.create(date=transaction.date, product=item.product, quantity=item.damage_quantity, related_transaction=transaction, reason="Updated during invoice edit")
                reconciliation, _ = PaymentReconciliation.objects.get_or_create(transaction=transaction)
                for field in ("cash", "expenses", "credit", "discount", "others"):
                    setattr(reconciliation, field, request.POST.get(field) or 0)
                reconciliation.save()
                currency_count = CurrencyCount.objects.filter(transaction=transaction).first()
                if currency_count or request.POST.get("currency_count_active") == "1":
                    currency_count = update_currency_count_from_request(
                        request, currency_count or CurrencyCount(transaction=transaction)
                    )
                    reconciliation.cash = currency_count.total_cash
                    reconciliation.save()
                transaction.notes = request.POST.get("notes", "").strip()
                if transaction.status == SalesTransaction.Status.PENDING:
                    if save_action == "finalize" and not transaction.items.exists():
                        raise ValueError("Add at least one product before final save.")
                    transaction.status = SalesTransaction.Status.FINALIZED if save_action == "finalize" else SalesTransaction.Status.PENDING
                else:
                    transaction.status = SalesTransaction.Status.FINALIZED
                transaction.save(update_fields=["notes", "status", "updated_at"])
            if transaction.status == SalesTransaction.Status.PENDING:
                return redirect(f"{reverse('pending-sales')}?date={transaction.date.isoformat()}")
            return redirect("daily-summary-date", transaction.date.isoformat())
        except StockShortageWarning as exc:
            stock_warnings = exc.warnings
            stock_confirmation_signature = _stock_confirmation_signature((item.pk, request.POST.get(f"order_quantity_{item.pk}") or item.order_quantity) for item in transaction.items.all())
            error = "Stock warning: confirm the quantities below to save anyway."
            transaction = SalesTransaction.objects.select_related("route").prefetch_related("items", "reconciliation").get(pk=pk)
            _apply_edit_form_data(transaction, request.POST)
            currency_count = CurrencyCount.objects.filter(transaction=transaction).first()
            template_name = "sales/pending_edit.html" if transaction.status == SalesTransaction.Status.PENDING else "sales/edit.html"
            reconciliation = PaymentReconciliation.objects.filter(transaction=transaction).first()
            return render(request, template_name, {"transaction": transaction, "reconciliation": reconciliation, "error": error, "stock_warnings": stock_warnings, "stock_confirmation_signature": stock_confirmation_signature, "form_data": request.POST, **currency_count_context(currency_count, request.POST)})
        except Exception as exc:
            logger.exception("Daily Sales invoice edit failed")
            transaction = SalesTransaction.objects.select_related("route").prefetch_related("items", "reconciliation").get(pk=pk)
            _apply_edit_form_data(transaction, request.POST)
            currency_count = CurrencyCount.objects.filter(transaction=transaction).first()
            template_name = "sales/pending_edit.html" if transaction.status == SalesTransaction.Status.PENDING else "sales/edit.html"
            reconciliation = PaymentReconciliation.objects.filter(transaction=transaction).first()
            return render(request, template_name, {"transaction": transaction, "reconciliation": reconciliation, "error": str(exc), "stock_warnings": stock_warnings, "stock_confirmation_signature": stock_confirmation_signature, "form_data": request.POST, **currency_count_context(currency_count, request.POST)})
    currency_count = CurrencyCount.objects.filter(transaction=transaction).first()
    reconciliation = PaymentReconciliation.objects.filter(transaction=transaction).first()
    return render(request, template_name, {"transaction": transaction, "reconciliation": reconciliation, "stock_warnings": stock_warnings, **currency_count_context(currency_count)})


def product_history(request, product_id):
    from django.shortcuts import get_object_or_404

    group = get_current_group(request)
    product = get_object_or_404(Product, pk=product_id, group=group)
    items = SalesItem.objects.filter(group=group, product=product).select_related("transaction", "transaction__route").order_by("transaction__date", "transaction__created_at")
    return render(request, "sales/product_history.html", {
        "product": product,
        "items": items,
        "totals": {
            "order": sum((item.order_quantity for item in items), Decimal("0")),
            "return": sum((item.return_quantity for item in items), Decimal("0")),
            "sale": sum((item.sale_quantity for item in items), Decimal("0")),
            "damage": sum((item.damage_quantity for item in items), Decimal("0")),
            "value": sum((item.sale_value for item in items), Decimal("0")),
        },
    })
