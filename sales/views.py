from calendar import month_name
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO
import hashlib
import logging

from django.db import IntegrityError
from django.db.models import Count
from django.db import transaction as db_transaction
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.html import escape

from dealers.context import get_current_group
from dealers.models import Dealer, Route
from godown_stock.services import stock_balances, stock_display
from inventory.models import Damage, StockTransaction
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


def _nonnegative_decimal(value, label):
    try:
        quantity = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Enter a valid {label}.") from exc
    if quantity < 0:
        raise ValueError(f"{label.capitalize()} cannot be negative.")
    return quantity


def _pending_product_groups(group):
    products = list(
        Product.objects.filter(group=group, active=True)
        .select_related("category")
        .order_by("category__name", "name")
    )
    return [
        (category.name, [product for product in products if product.category_id == category.id])
        for category in group.categories.filter(active=True)
    ]


def _set_item_product_snapshot(item, product):
    item.product = product
    item.product_id_snapshot = product.pk
    item.product_name_snapshot = product.name
    item.category_snapshot = product.category.name
    item.ctn_size_snapshot = product.ctn_size
    item.dealer_price_snapshot = product.dealer_price
    item.trade_price_snapshot = product.trade_price
    item.sale_price_snapshot = product.effective_sale_price
    item.foc_snapshot = product.foc


def _save_pending_item_rows(transaction, group, form_data):
    """Save editable PCS-based lines for an existing Pending invoice only."""
    fields = (
        "item_id",
        "product_id",
        "order_quantity",
        "return_quantity",
        "foc_quantity",
        "free_product_quantity",
        "damage_quantity",
        "line_discount",
    )
    values = {field: form_data.getlist(field) for field in fields}
    existing = {item.pk: item for item in transaction.items.select_related("product").all()}
    rows = []
    submitted_item_ids = set()
    selected_product_ids = set()

    for index, product_id in enumerate(values["product_id"]):
        def value(field, default="0"):
            return values[field][index] if index < len(values[field]) else default

        if not product_id:
            if any(
                _nonnegative_decimal(value(field), field.replace("_", " "))
                for field in fields[2:]
            ):
                raise ValueError("Select a product for every non-empty pending row.")
            continue
        try:
            product = Product.objects.get(pk=product_id, group=group, active=True)
        except (Product.DoesNotExist, ValueError) as exc:
            raise ValueError("Select an active product from Product Setup.") from exc
        if product.pk in selected_product_ids:
            raise ValueError("A product can appear only once on a pending invoice.")
        selected_product_ids.add(product.pk)

        item = None
        raw_item_id = value("item_id", "")
        if raw_item_id:
            try:
                item = existing[int(raw_item_id)]
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("One of the pending product rows is no longer available.") from exc
            if item.pk in submitted_item_ids:
                raise ValueError("A pending product row was submitted more than once.")
            submitted_item_ids.add(item.pk)

        rows.append(
            {
                "item": item,
                "product": product,
                "order_quantity": _nonnegative_decimal(value("order_quantity"), "order quantity"),
                "return_quantity": _nonnegative_decimal(value("return_quantity"), "return quantity"),
                "foc_quantity": _nonnegative_decimal(value("foc_quantity"), "FOC quantity"),
                "free_product_quantity": _nonnegative_decimal(value("free_product_quantity"), "free product quantity"),
                "damage_quantity": _nonnegative_decimal(value("damage_quantity"), "damage quantity"),
                "discount": _nonnegative_decimal(value("line_discount"), "line discount"),
            }
        )

    stale_item_ids = set(existing) - submitted_item_ids
    if stale_item_ids:
        SalesItem.objects.filter(pk__in=stale_item_ids).delete()

    changed_item_ids = [
        row["item"].pk
        for row in rows
        if row["item"] is not None and row["item"].product_id != row["product"].pk
    ]
    if changed_item_ids:
        # Clear product references first so swapping two existing product rows
        # cannot violate the one-product-per-invoice constraint mid-save.
        SalesItem.objects.filter(pk__in=changed_item_ids).update(product=None)

    saved_items = []
    for row in rows:
        item = row["item"] or SalesItem(transaction=transaction)
        if row["item"] is None or item.product_id != row["product"].pk:
            _set_item_product_snapshot(item, row["product"])
        for field in (
            "order_quantity",
            "return_quantity",
            "foc_quantity",
            "free_product_quantity",
            "damage_quantity",
            "discount",
        ):
            setattr(item, field, row[field])
        item.save()
        saved_items.append(item)
    return saved_items


def _pending_stock_confirmation_signature(group, form_data):
    values = []
    product_ids = form_data.getlist("product_id")
    order_quantities = form_data.getlist("order_quantity")
    for index, product_id in enumerate(product_ids):
        if not product_id:
            continue
        try:
            product = Product.objects.get(pk=product_id, group=group, active=True)
        except (Product.DoesNotExist, ValueError):
            continue
        quantity = order_quantities[index] if index < len(order_quantities) else "0"
        values.append((product.pk, quantity))
    return _stock_confirmation_signature(values)


def _record_finalized_inventory_effects(transaction, items):
    """Apply inventory effects once, when a Daily Sales invoice is finalized."""
    for item in items:
        if item.damage_quantity:
            damage = Damage.objects.create(
                date=transaction.date,
                product=item.product,
                quantity=item.damage_quantity,
                related_transaction=transaction,
                reason="Recorded on finalized daily sales invoice",
            )
            StockTransaction.record_damage(damage)
        StockTransaction.record_sale_item(item)
        StockTransaction.record_return_item(item)


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
                items = []
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
                    items.append(item)

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
                if save_action == "finalize":
                    _record_finalized_inventory_effects(sale, items)
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
    invoices_pdf_export_url = f"/reports/monthly/export/invoices/pdf/{export_query}"
    return render(request, "sales/daily_summary.html", {"transactions": transactions, "daily_records": daily_records, "product_details": sorted(product_details.values(), key=lambda detail: (detail["category"], detail["name"].lower())), "totals": totals, "selected_date": selected_date, "selected_year": selected_year, "selected_month": selected_month, "selected_route_id": route_id, "routes": Route.objects.filter(group=group, active=True), "month_options": [(number, month_name[number]) for number in range(1, 13)], "excel_export_url": excel_export_url, "pdf_export_url": pdf_export_url, "invoices_pdf_export_url": invoices_pdf_export_url, "period_label": selected_date.strftime("%d %B %Y") if selected_date else f"{month_name[selected_month]} {selected_year}"})


def _finalized_invoice_for_current_group(request, pk):
    group = get_current_group(request)
    transaction = get_object_or_404(
        SalesTransaction.objects.filter(group=group, status=SalesTransaction.Status.FINALIZED)
        .select_related("route", "dealer", "reconciliation")
        .prefetch_related("items__product", "damages"),
        pk=pk,
    )
    return group, transaction


def sales_invoice_detail(request, pk):
    """Render a finalized invoice as report history, never as an edit form."""
    _, transaction = _finalized_invoice_for_current_group(request, pk)
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


def sales_invoice_pdf(request, pk):
    """Render the read-only invoice detail view as a print-ready PDF."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    group, transaction = _finalized_invoice_for_current_group(request, pk)
    reconciliation = getattr(transaction, "reconciliation", None)
    currency_count = CurrencyCount.objects.filter(transaction=transaction).first()
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=landscape(A4),
        leftMargin=8 * mm,
        rightMargin=8 * mm,
        topMargin=12 * mm,
        bottomMargin=14 * mm,
        title=f"{transaction.invoice_number} - {group.name}",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "InvoicePdfTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=17,
        textColor=colors.HexColor("#1D3330"),
        alignment=TA_CENTER,
        spaceAfter=3,
    )
    kicker_style = ParagraphStyle(
        "InvoicePdfKicker",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#3A9C91"),
        spaceAfter=4,
    )
    detail_style = ParagraphStyle(
        "InvoicePdfDetail",
        parent=styles["Normal"],
        fontSize=8,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#627D8A"),
        spaceAfter=12,
    )
    metadata_style = ParagraphStyle(
        "InvoicePdfMetadata",
        parent=styles["Normal"],
        fontSize=7.5,
        leading=9,
    )
    product_style = ParagraphStyle(
        "InvoicePdfProduct",
        parent=styles["Normal"],
        fontSize=5.8,
        leading=6.8,
    )
    product_name_style = ParagraphStyle(
        "InvoicePdfProductName",
        parent=product_style,
        fontName="Helvetica-Bold",
    )
    header_style = ParagraphStyle(
        "InvoicePdfHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=5.7,
        leading=6.5,
        textColor=colors.HexColor("#627D8A"),
        alignment=TA_CENTER,
    )
    section_title_style = ParagraphStyle(
        "InvoicePdfSectionTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        textColor=colors.HexColor("#1D3330"),
    )
    section_caption_style = ParagraphStyle(
        "InvoicePdfSectionCaption",
        parent=styles["Normal"],
        fontSize=7,
        textColor=colors.HexColor("#627D8A"),
        alignment=TA_CENTER,
    )

    def money(value):
        return f"{value:.2f}"

    def metadata_cell(value):
        return Paragraph(escape(str(value)), metadata_style)

    def product_cell(value, style=product_style):
        return Paragraph(escape(str(value)), style)

    def table_header(value):
        return Paragraph(value, header_style)

    def section_heading(title, caption):
        table = Table(
            [[Paragraph(title, section_title_style), Paragraph(caption, section_caption_style)]],
            colWidths=[180 * mm, 88 * mm],
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7FAF9")),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.6, colors.HexColor("#C8D6D3")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        return table

    story = [
        Paragraph(escape(group.name), kicker_style),
        Paragraph(f"Invoice {escape(transaction.invoice_number)}", title_style),
        Paragraph("FINALIZED - Read-only invoice detail", detail_style),
        section_heading("Invoice Details", "Saved invoice values"),
    ]
    metadata = [
        [table_header("Date"), table_header("Route"), table_header("Day"), table_header("Invoice Number"), table_header("Notes")],
        [
            metadata_cell(transaction.date.strftime("%d %b %Y")),
            metadata_cell(transaction.route_display),
            metadata_cell(transaction.route_day or transaction.date.strftime("%A")),
            metadata_cell(transaction.invoice_number),
            metadata_cell(transaction.notes),
        ],
    ]
    metadata_table = Table(metadata, colWidths=[38 * mm, 53 * mm, 36 * mm, 57 * mm, 84 * mm], repeatRows=1)
    metadata_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF4F2")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E9EFEE")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.extend([metadata_table, Spacer(1, 12), section_heading("Product Lines", "All quantities, prices, and values are preserved from the finalized invoice."), Spacer(1, 4)])

    product_rows = [[
        table_header("Product"), table_header("Category"), table_header("CTN"), table_header("Dealer<br/>price"),
        table_header("Trade<br/>price"), table_header("FOC<br/>price"), table_header("Sale<br/>price"),
        table_header("Order<br/>qty"), table_header("Order<br/>value"), table_header("Return<br/>qty"),
        table_header("Return<br/>value"), table_header("Sale<br/>qty"), table_header("Sale<br/>value"),
        table_header("Damage<br/>qty"), table_header("Damage<br/>value"), table_header("Free<br/>product"),
        table_header("Free<br/>value"), table_header("Line<br/>discount"),
    ]]
    items = list(transaction.items.all())
    for item in items:
        product_rows.append(
            [
                product_cell(item.product_name_snapshot, product_name_style), product_cell(item.category_snapshot), str(item.ctn_size_snapshot),
                money(item.dealer_price_snapshot), money(item.trade_price_snapshot), money(item.foc_snapshot), money(item.sale_price_snapshot),
                f"{item.order_quantity:.2f}", money(item.order_value), f"{item.return_quantity:.2f}", money(item.return_value),
                f"{item.sale_quantity:.2f}", money(item.sale_value), f"{item.damage_quantity:.2f}", money(item.damage_value),
                f"{item.free_product_quantity:.2f}", money(item.free_product_value), money(item.discount),
            ]
        )
    if not items:
        product_rows.append(["No product lines were saved on this invoice."] + [""] * 17)
    products_table = Table(
        product_rows,
        colWidths=[26 * mm, 17 * mm, 8 * mm, 15 * mm, 15 * mm, 15 * mm, 15 * mm, 12 * mm, 16 * mm, 12 * mm, 16 * mm, 12 * mm, 16 * mm, 12 * mm, 16 * mm, 12 * mm, 16 * mm, 17 * mm],
        repeatRows=1,
    )
    products_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF4F2")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#627D8A")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 5.8),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E9EFEE")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    if not items:
        products_table.setStyle(TableStyle([("SPAN", (0, 1), (-1, 1)), ("ALIGN", (0, 1), (-1, 1), "LEFT")]))
    story.extend([products_table, Spacer(1, 12), section_heading("Invoice Totals", "Quantity / pieces use the saved invoice CTN size."), Spacer(1, 4)])

    quantity_rows = [
        [table_header("Sent qty /<br/>pieces"), table_header("Sale qty /<br/>pieces"), table_header("Return qty /<br/>pieces"), table_header("Damage qty /<br/>pieces")],
        [
            f"{transaction.sent_quantity_total:.2f} / {transaction.sent_pieces_total:.2f}",
            f"{transaction.sale_quantity_total:.2f} / {transaction.sale_pieces_total:.2f}",
            f"{transaction.return_quantity_total:.2f} / {transaction.return_pieces_total:.2f}",
            f"{transaction.damage_quantity_total:.2f} / {transaction.damage_pieces_total:.2f}",
        ],
    ]
    financial_rows = [
        [table_header("Order value"), table_header("Total sale"), table_header("Total damage"), table_header("Total discount"), table_header("Free product value"), table_header("Net sale")],
        [
            money(transaction.order_total),
            money(transaction.sale_total),
            money(transaction.damage_total),
            money(transaction.total_discount),
            money(transaction.free_product_total),
            money(transaction.net_sale),
        ],
    ]
    payment_rows = [
        [table_header("Grand total sale"), table_header("Cash"), table_header("Expenses"), table_header("Credit"), table_header("Discount"), table_header("Others"), table_header("Shortage / variance")],
        [
            money(transaction.grand_total_sale),
            money(getattr(reconciliation, "cash", Decimal("0"))),
            money(getattr(reconciliation, "expenses", Decimal("0"))),
            money(getattr(reconciliation, "credit", Decimal("0"))),
            money(getattr(reconciliation, "discount", Decimal("0"))),
            money(getattr(reconciliation, "others", Decimal("0"))),
            money(getattr(reconciliation, "shortage", transaction.grand_total_sale)),
        ],
    ]

    def summary_table(rows, widths, alignment="RIGHT"):
        table = Table(rows, colWidths=widths)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF4F2")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#627D8A")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("ALIGN", (0, 0), (-1, -1), alignment),
                    ("FONTSIZE", (0, 0), (-1, -1), 6.5),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E9EFEE")),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        return table

    story.extend(
        [
            summary_table(quantity_rows, [63 * mm] * 4, alignment="CENTER"),
            Spacer(1, 5),
            summary_table(financial_rows, [42 * mm] * 6),
            Spacer(1, 12),
            section_heading("Payment Reconciliation", "Saved payment details"),
            Spacer(1, 4),
            summary_table(payment_rows, [36 * mm] * 7),
        ]
    )
    if currency_count:
        currency_rows = [[table_header("Note"), table_header("Quantity"), table_header("Total")]]
        currency_rows.extend([[str(note), str(quantity), money(total)] for note, quantity, total in currency_count.rows])
        currency_rows.append(["Total cash", "", money(currency_count.total_cash)])
        currency_table = Table(currency_rows, colWidths=[40 * mm, 40 * mm, 52 * mm], hAlign="LEFT", repeatRows=1)
        currency_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D5EBC5")),
                    ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E7D9A5")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C8D6D3")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.extend([Spacer(1, 12), section_heading("Currency Count", "Saved physical cash count"), Spacer(1, 4), currency_table])

    def draw_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#627D8A"))
        canvas.drawString(doc.leftMargin, 8 * mm, f"{group.name} - Invoice {transaction.invoice_number}")
        canvas.drawRightString(landscape(A4)[0] - doc.rightMargin, 8 * mm, f"Page {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    response = HttpResponse(output.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{transaction.invoice_number}.pdf"'
    return response


def sales_edit(request, pk):
    group = get_current_group(request)
    transaction = get_object_or_404(SalesTransaction.objects.filter(group=group).select_related("route").prefetch_related("items", "reconciliation"), pk=pk)

    def pending_context(current_transaction):
        if current_transaction.status == SalesTransaction.Status.PENDING:
            return {"product_groups": _pending_product_groups(group)}
        return {}

    template_name = "sales/pending_edit.html" if transaction.status == SalesTransaction.Status.PENDING else "sales/edit.html"
    stock_warnings = []
    stock_confirmation_signature = ""
    if request.method == "POST":
        try:
            with db_transaction.atomic():
                transaction = SalesTransaction.objects.select_for_update().get(pk=pk, group=group)
                was_pending = transaction.status == SalesTransaction.Status.PENDING
                save_action = request.POST.get("save_action", "pending" if transaction.status == SalesTransaction.Status.PENDING else "finalize")
                if request.POST.get("confirm_short_stock") == "1":
                    save_action = "finalize"
                if save_action not in {"pending", "finalize"}:
                    raise ValueError("Unknown save action.")
                if was_pending and "item_id" in request.POST:
                    items = _save_pending_item_rows(transaction, group, request.POST)
                    if save_action == "finalize":
                        confirmation = (
                            request.POST.get("confirm_short_stock")
                            if request.POST.get("stock_confirmation_signature")
                            == _pending_stock_confirmation_signature(group, request.POST)
                            else None
                        )
                        _validate_edit_stock_requirements(transaction, items, confirmation)
                else:
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
                        if not was_pending:
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
                if was_pending and transaction.status == SalesTransaction.Status.FINALIZED:
                    _record_finalized_inventory_effects(transaction, items)
            if transaction.status == SalesTransaction.Status.PENDING:
                return redirect(f"{reverse('pending-sales')}?date={transaction.date.isoformat()}")
            return redirect("daily-summary-date", transaction.date.isoformat())
        except StockShortageWarning as exc:
            stock_warnings = exc.warnings
            stock_confirmation_signature = (
                _pending_stock_confirmation_signature(group, request.POST)
                if transaction.status == SalesTransaction.Status.PENDING and "item_id" in request.POST
                else _stock_confirmation_signature((item.pk, request.POST.get(f"order_quantity_{item.pk}") or item.order_quantity) for item in transaction.items.all())
            )
            error = "Stock warning: confirm the quantities below to save anyway."
            transaction = SalesTransaction.objects.select_related("route").prefetch_related("items", "reconciliation").get(pk=pk)
            _apply_edit_form_data(transaction, request.POST)
            currency_count = CurrencyCount.objects.filter(transaction=transaction).first()
            template_name = "sales/pending_edit.html" if transaction.status == SalesTransaction.Status.PENDING else "sales/edit.html"
            reconciliation = PaymentReconciliation.objects.filter(transaction=transaction).first()
            return render(request, template_name, {"transaction": transaction, "reconciliation": reconciliation, "error": error, "stock_warnings": stock_warnings, "stock_confirmation_signature": stock_confirmation_signature, "form_data": request.POST, **currency_count_context(currency_count, request.POST), **pending_context(transaction)})
        except Exception as exc:
            logger.exception("Daily Sales invoice edit failed")
            transaction = SalesTransaction.objects.select_related("route").prefetch_related("items", "reconciliation").get(pk=pk)
            _apply_edit_form_data(transaction, request.POST)
            currency_count = CurrencyCount.objects.filter(transaction=transaction).first()
            template_name = "sales/pending_edit.html" if transaction.status == SalesTransaction.Status.PENDING else "sales/edit.html"
            reconciliation = PaymentReconciliation.objects.filter(transaction=transaction).first()
            return render(request, template_name, {"transaction": transaction, "reconciliation": reconciliation, "error": str(exc), "stock_warnings": stock_warnings, "stock_confirmation_signature": stock_confirmation_signature, "form_data": request.POST, **currency_count_context(currency_count, request.POST), **pending_context(transaction)})
    currency_count = CurrencyCount.objects.filter(transaction=transaction).first()
    reconciliation = PaymentReconciliation.objects.filter(transaction=transaction).first()
    return render(request, template_name, {"transaction": transaction, "reconciliation": reconciliation, "stock_warnings": stock_warnings, **currency_count_context(currency_count), **pending_context(transaction)})


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
