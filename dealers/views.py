import re
from calendar import month_name
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import logout
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render

from .credit import dealer_aging, dealer_ledger
from .models import Dealer, DealerCredit, DealerPayment, Group, Route, next_dealer_code


def group_select(request):
    groups = Group.objects.filter(active=True).order_by("name", "id")
    current_group_id = request.session.get("current_group_id")
    theme_palette = ["green", "orange", "blue", "purple", "teal"]
    group_data = []
    for idx, g in enumerate(groups):
        words = g.name.strip().split()
        if g.name == "BD Foods":
            short_code = "BF"
            initials = "BF"
            theme = "green"
        elif g.name == "Gold mark":
            short_code = "GM"
            initials = "GM"
            theme = "orange"
        elif g.name == "New Zealand Dairy":
            short_code = "NZ"
            initials = "NZ"
            theme = "blue"
        elif len(words) >= 2:
            short_code = "".join(w[0] for w in words)[:4].upper()
            initials = (words[0][0] + words[1][0]).upper()
        elif words and len(words[0]) >= 2:
            short_code = words[0][:3].upper()
            initials = words[0][:2].upper()
        elif words and len(words[0]) == 1:
            short_code = words[0][0].upper()
            initials = words[0][0].upper()
        else:
            short_code = "GP"
            initials = "GP"
        theme = theme_palette[idx % len(theme_palette)]
        group_data.append({
            "group": g,
            "initials": initials,
            "short_code": short_code,
            "theme": theme,
            "is_current": g.pk == current_group_id,
            "dealers_count": g.dealers.count(),
            "products_count": g.products.count(),
        })
    return render(request, "groups/select.html", {
        "groups": group_data,
        "current_group_id": current_group_id,
    })


def open_group(request, pk):
    group = Group.objects.filter(pk=pk, active=True).first()
    if not group:
        messages.error(request, "The selected business group is not available.")
        return redirect("group-select")
    request.session["current_group_id"] = group.pk
    messages.success(request, f"Switched to {group.name}.")
    return redirect("dashboard")


def logout_view(request):
    logout(request)
    request.session.flush()
    messages.info(request, "You have been logged out.")
    return redirect("group-select")


def switch_group(request):
    if request.method != "POST":
        return redirect("group-select")
    group_id = request.POST.get("group_id")
    group = Group.objects.filter(pk=group_id, active=True).first()
    if not group:
        messages.error(request, "The selected business group is not available.")
        return redirect("group-select")
    request.session["current_group_id"] = group.pk
    next_url = request.POST.get("next", "").strip()
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/dashboard/"
    else:
        # Sanitize next_url: Never carry forward object IDs specific to a group
        if re.match(r"^/credit/dealers/\d+", next_url) or next_url.startswith("/credit/dealers/new/"):
            next_url = "/credit/"
        elif re.match(r"^/godown-stock/history/(challan/\d+|\d+)", next_url):
            next_url = "/godown-stock/history/"
        elif re.match(r"^/sales/transactions/\d+", next_url):
            next_url = "/sales/"
        elif re.match(r"^/products/\d+", next_url):
            next_url = "/product-setup/"
    return redirect(next_url)


def create_group(request):
    error = None
    if request.method == "POST":
        group = Group(name=request.POST.get("name", "").strip())
        try:
            group.full_clean()
            group.save()
        except ValidationError as exc:
            error = "; ".join(sum(exc.message_dict.values(), []))
        if error is None:
            request.session["current_group_id"] = group.pk
            messages.success(request, f"{group.name} is now the current group.")
            return redirect("dashboard")
    return render(request, "groups/create.html", {"error": error})


def delete_group(request, pk):
    if request.method != "POST":
        return redirect("dashboard")
    with transaction.atomic():
        group = get_object_or_404(Group.objects.select_for_update(), pk=pk)
        if not group.is_empty:
            messages.error(request, f"{group.name} contains business data and cannot be deleted.")
            return redirect("dashboard")
        group_name = group.name
        try:
            group.delete()
        except ProtectedError:
            messages.error(request, f"{group.name} now contains business data and cannot be deleted.")
            return redirect("dashboard")
        if request.session.get("current_group_id") == pk:
            replacement = Group.objects.filter(active=True).order_by("id").first()
            if replacement:
                request.session["current_group_id"] = replacement.pk
            else:
                request.session.pop("current_group_id", None)
    messages.success(request, f"{group_name} was deleted permanently.")
    next_url = request.POST.get("next", "").strip()
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/dashboard/"
    else:
        if re.match(r"^/credit/dealers/\d+", next_url) or next_url.startswith("/credit/dealers/new/"):
            next_url = "/credit/"
        elif re.match(r"^/godown-stock/history/(challan/\d+|\d+)", next_url):
            next_url = "/godown-stock/history/"
    return redirect(next_url)


def _dealer_context(group):
    return {"routes": Route.objects.filter(group=group, active=True).order_by("route_name", "id"), "current_group": group}


def _get_scoped_dealer(request, pk, group):
    """
    Safely retrieve a dealer for the given group context.
    If the dealer belongs to a different group, adds a user-friendly warning message
    and returns (None, redirect_response).
    If the dealer doesn't exist, adds a user-friendly warning message and returns (None, redirect_response).
    Otherwise returns (dealer, None).
    """
    dealer = Dealer.objects.filter(pk=pk).select_related("group", "route").first()
    if dealer is None:
        messages.warning(request, "The requested dealer was not found.")
        return None, redirect("dealer-list")
    if dealer.group_id != group.pk:
        messages.warning(
            request,
            f"'{dealer.name}' belongs to group '{dealer.group.name}'. Please switch to '{dealer.group.name}' to view or edit their credit record.",
        )
        return None, redirect("dealer-list")
    return dealer, None


def dealer_list(request):
    group = Group.objects.filter(active=True, pk=request.session.get("current_group_id")).first() or Group.default()
    dealers = Dealer.objects.filter(group=group).select_related("route")
    query = request.GET.get("q", "").strip()
    route_id = request.GET.get("route", "")
    due_filter = request.GET.get("due", "")
    status_filter = request.GET.get("status", "active")
    if query:
        dealers = dealers.filter(name__icontains=query) | dealers.filter(code__icontains=query) | dealers.filter(phone__icontains=query) | dealers.filter(location__icontains=query)
    if route_id:
        dealers = dealers.filter(route_id=route_id, group=group)
    if status_filter in ("active", "inactive"):
        dealers = dealers.filter(active=status_filter == "active")
    rows = []
    for dealer in dealers.distinct().order_by("name", "id"):
        payments = dealer.payments.order_by("-payment_date", "-created_at")
        due = dealer.current_due
        if due_filter == "due" and due <= 0 or due_filter == "clear" and due > 0:
            continue
        rows.append({"dealer": dealer, "due": due, "last_payment": payments.first()})
    today = date.today()
    month_payments = DealerPayment.objects.filter(group=group, payment_date__year=today.year, payment_date__month=today.month)
    totals = {
        "dealers": len(rows),
        "with_due": sum(1 for row in rows if row["due"] > 0),
        "clear": sum(1 for row in rows if row["due"] <= 0),
        "outstanding": sum((row["due"] for row in rows), Decimal("0")),
        "payments": sum((payment.amount for payment in month_payments), Decimal("0")),
    }
    return render(request, "dealers/list.html", {"rows": rows, "totals": totals, "query": query, "route_id": route_id, "due_filter": due_filter, "status_filter": status_filter, **_dealer_context(group)})


def dealer_create(request):
    group = Group.objects.filter(active=True, pk=request.session.get("current_group_id")).first() or Group.default()
    dealer_code = next_dealer_code(group)
    if request.method == "POST":
        try:
            route = Route.objects.filter(pk=request.POST.get("route"), group=group).first()
            if route is None:
                raise ValidationError({"route": "Select a route for this dealer."})
            dealer = Dealer(
                group=group,
                name=request.POST.get("name", "").strip(),
                code=next_dealer_code(group),
                route=route,
                address=request.POST.get("address", "").strip(),
                location=request.POST.get("location", "").strip(),
                phone=request.POST.get("phone", "").strip(),
                contact_person=request.POST.get("contact_person", "").strip(),
                opening_due=request.POST.get("opening_due") or 0,
                memo=request.POST.get("memo", "").strip(),
                memo_image=request.FILES.get("memo_image"),
            )
            dealer.save()
            messages.success(request, f"{dealer.name} was added.")
            return redirect("dealer-detail", dealer.pk)
        except (ValidationError, InvalidOperation, TypeError, ValueError) as exc:
            return render(request, "dealers/form.html", {"dealer": locals().get("dealer"), "dealer_code": dealer_code, "error": str(exc), **_dealer_context(group)})
    return render(request, "dealers/form.html", {"dealer": None, "dealer_code": dealer_code, **_dealer_context(group)})


def dealer_edit(request, pk):
    group = Group.objects.filter(active=True, pk=request.session.get("current_group_id")).first() or Group.default()
    dealer, error_redirect = _get_scoped_dealer(request, pk, group)
    if error_redirect:
        return error_redirect
    dealer_code = dealer.code
    if request.method == "POST":
        try:
            dealer.name = request.POST.get("name", "").strip()
            route = Route.objects.filter(pk=request.POST.get("route"), group=group).first()
            if not route:
                raise ValidationError({"route": "Select a route for this dealer."})
            dealer.route = route
            dealer.address = request.POST.get("address", "").strip()
            dealer.location = request.POST.get("location", "").strip()
            dealer.phone = request.POST.get("phone", "").strip()
            dealer.contact_person = request.POST.get("contact_person", "").strip()
            dealer.opening_due = Decimal(request.POST.get("opening_due") or 0)
            dealer.memo = request.POST.get("memo", "").strip()
            if request.POST.get("remove_memo_image") == "1" and dealer.memo_image:
                dealer.memo_image.delete(save=False)
                dealer.memo_image = None
            if request.FILES.get("memo_image"):
                dealer.memo_image = request.FILES["memo_image"]
            dealer.save()
            messages.success(request, "Dealer details updated.")
            return redirect("dealer-detail", dealer.pk)
        except (ValidationError, InvalidOperation, TypeError, ValueError) as exc:
            return render(request, "dealers/form.html", {"dealer": dealer, "dealer_code": dealer_code, "error": str(exc), **_dealer_context(group)})
    return render(request, "dealers/form.html", {"dealer": dealer, "dealer_code": dealer_code, **_dealer_context(group)})


def dealer_detail(request, pk):
    group = Group.objects.filter(active=True, pk=request.session.get("current_group_id")).first() or Group.default()
    dealer, error_redirect = _get_scoped_dealer(request, pk, group)
    if error_redirect:
        return error_redirect
    invoices = dealer.sales_transactions.filter(status="FINALIZED").order_by("-date", "-created_at")
    return render(request, "dealers/detail.html", {"dealer": dealer, "ledger": dealer_ledger(dealer), "due": dealer.current_due, "aging": dealer_aging(dealer), "payments": dealer.payments.order_by("-payment_date", "-created_at"), "invoices": invoices, "can_delete": dealer.current_due <= 0, **_dealer_context(group)})


def dealer_payment(request, pk):
    group = Group.objects.filter(active=True, pk=request.session.get("current_group_id")).first() or Group.default()
    dealer, error_redirect = _get_scoped_dealer(request, pk, group)
    if error_redirect:
        return error_redirect
    if request.method == "POST":
        try:
            payment = DealerPayment(
                group=group,
                dealer=dealer,
                payment_date=date.fromisoformat(request.POST.get("payment_date") or date.today().isoformat()),
                amount=Decimal(request.POST.get("amount") or 0),
                method=request.POST.get("method") or DealerPayment.CASH,
                reference=request.POST.get("reference", "").strip(),
                notes=request.POST.get("notes", "").strip(),
            )
            payment.save()
            messages.success(request, f"Payment of {payment.amount:.2f} received.")
            return redirect("dealer-detail", dealer.pk)
        except (ValidationError, InvalidOperation, TypeError, ValueError) as exc:
            return render(request, "dealers/payment.html", {"dealer": dealer, "error": str(exc), "methods": DealerPayment.PAYMENT_METHODS, "today": date.today(), **_dealer_context(group)})
    return render(request, "dealers/payment.html", {"dealer": dealer, "methods": DealerPayment.PAYMENT_METHODS, "today": date.today(), **_dealer_context(group)})


def dealer_credit(request, pk):
    group = Group.objects.filter(active=True, pk=request.session.get("current_group_id")).first() or Group.default()
    dealer, error_redirect = _get_scoped_dealer(request, pk, group)
    if error_redirect:
        return error_redirect
    if request.method == "POST":
        try:
            credit = DealerCredit(
                group=group,
                dealer=dealer,
                credit_date=date.fromisoformat(request.POST.get("credit_date") or date.today().isoformat()),
                amount=Decimal(request.POST.get("amount") or 0),
                reference=request.POST.get("reference", "").strip() or "Manual credit",
                notes=request.POST.get("notes", "").strip(),
            )
            credit.save()
            messages.success(request, f"Credit of {credit.amount:.2f} added.")
            return redirect("dealer-detail", dealer.pk)
        except (ValidationError, InvalidOperation, TypeError, ValueError) as exc:
            return render(request, "dealers/credit.html", {"dealer": dealer, "error": str(exc), "today": date.today(), **_dealer_context(group)})
    return render(request, "dealers/credit.html", {"dealer": dealer, "today": date.today(), **_dealer_context(group)})


def dealer_statement(request, pk):
    group = Group.objects.filter(active=True, pk=request.session.get("current_group_id")).first() or Group.default()
    dealer, error_redirect = _get_scoped_dealer(request, pk, group)
    if error_redirect:
        return error_redirect
    return render(request, "dealers/statement.html", {"dealer": dealer, "ledger": dealer_ledger(dealer), "due": dealer.current_due, **_dealer_context(group)})


def dealer_delete(request, pk):
    group = Group.objects.filter(active=True, pk=request.session.get("current_group_id")).first() or Group.default()
    dealer, error_redirect = _get_scoped_dealer(request, pk, group)
    if error_redirect:
        return error_redirect
    if request.method == "POST":
        if dealer.current_due > 0:
            messages.error(request, "Dealer cannot be deleted while outstanding due exists.")
        else:
            try:
                dealer.delete()
                messages.success(request, "Dealer was deleted.")
            except ProtectedError:
                messages.error(request, "Dealer has historical invoices or payments and cannot be deleted. Deactivate it instead.")
        return redirect("dealer-list")
    return redirect("dealer-detail", dealer.pk)
