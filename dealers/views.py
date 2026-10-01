from calendar import month_name
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render

from .credit import dealer_aging, dealer_ledger
from .models import Dealer, DealerCredit, DealerPayment, Group, Route, next_dealer_code


def switch_group(request):
    if request.method != "POST":
        return redirect("dashboard")
    group = get_object_or_404(Group, pk=request.POST.get("group_id"), active=True)
    request.session["current_group_id"] = group.pk
    next_url = request.POST.get("next", "")
    return redirect(next_url if next_url.startswith("/") else "dashboard")


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
    next_url = request.POST.get("next", "")
    return redirect(next_url if next_url.startswith("/") else "dashboard")


def _dealer_context(group):
    return {"routes": Route.objects.filter(group=group, active=True).order_by("route_name", "id"), "current_group": group}


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
    dealer = get_object_or_404(Dealer, pk=pk, group=group)
    if request.method == "POST":
        try:
            dealer.name = request.POST.get("name", "").strip()
            dealer.route = Route.objects.filter(pk=request.POST.get("route"), group=group).first()
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
            return render(request, "dealers/form.html", {"dealer": dealer, "error": str(exc), **_dealer_context(group)})
    return render(request, "dealers/form.html", {"dealer": dealer, **_dealer_context(group)})


def dealer_detail(request, pk):
    group = Group.objects.filter(active=True, pk=request.session.get("current_group_id")).first() or Group.default()
    dealer = get_object_or_404(Dealer, pk=pk, group=group)
    invoices = dealer.sales_transactions.filter(status="FINALIZED").order_by("-date", "-created_at")
    return render(request, "dealers/detail.html", {"dealer": dealer, "ledger": dealer_ledger(dealer), "due": dealer.current_due, "aging": dealer_aging(dealer), "payments": dealer.payments.order_by("-payment_date", "-created_at"), "invoices": invoices, "can_delete": dealer.current_due <= 0, **_dealer_context(group)})


def dealer_payment(request, pk):
    group = Group.objects.filter(active=True, pk=request.session.get("current_group_id")).first() or Group.default()
    dealer = get_object_or_404(Dealer, pk=pk, group=group)
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
    dealer = get_object_or_404(Dealer, pk=pk, group=group)
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
    dealer = get_object_or_404(Dealer, pk=pk, group=group)
    return render(request, "dealers/statement.html", {"dealer": dealer, "ledger": dealer_ledger(dealer), "due": dealer.current_due, **_dealer_context(group)})


def dealer_delete(request, pk):
    group = Group.objects.filter(active=True, pk=request.session.get("current_group_id")).first() or Group.default()
    dealer = get_object_or_404(Dealer, pk=pk, group=group)
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
