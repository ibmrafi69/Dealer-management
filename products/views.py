from calendar import monthrange
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from dealers.context import get_current_group
from dealers.models import Dealer
from godown_stock.services import stock_rows
from sales.models import SalesTransaction

from .models import Category, Product


def _category_for_group(group, value):
	value = str(value or "").strip()
	if value.isdigit():
		return Category.objects.filter(pk=value, group=group).first()
	return Category.objects.filter(group=group, name__iexact=value).first()


def home(request):
	return render(request, "home.html")


def dashboard(request):
	group = get_current_group(request)
	today = date.today()
	try:
		selected_month = int(request.GET.get("month", today.month))
		selected_year = int(request.GET.get("year", today.year))
		if not 1 <= selected_month <= 12 or not 1 <= selected_year <= 9999:
			raise ValueError
	except (TypeError, ValueError):
		selected_month, selected_year = today.month, today.year

	base_transactions = SalesTransaction.objects.filter(group=group, status=SalesTransaction.Status.FINALIZED)
	month_transactions = list(
		base_transactions.filter(date__year=selected_year, date__month=selected_month)
		.select_related("route", "dealer", "reconciliation")
		.prefetch_related("items__product", "damages")
		.order_by("-date", "-created_at", "-pk")
	)
	today_transactions = list(
		base_transactions.filter(date=today)
		.select_related("route", "dealer", "reconciliation")
		.prefetch_related("items__product", "damages")
	)

	def metrics(transactions):
		return {
			"sales": sum((sale.sale_total for sale in transactions), Decimal("0")),
			"orders": len({sale.invoice_number for sale in transactions}),
			"returns": sum((sale.return_total for sale in transactions), Decimal("0")),
			"damage": sum((sale.damage_total for sale in transactions), Decimal("0")),
			"discount": sum((sale.total_discount for sale in transactions), Decimal("0")),
			"expenses": sum((getattr(getattr(sale, "reconciliation", None), "expenses", Decimal("0")) for sale in transactions), Decimal("0")),
			"shortage": sum((getattr(getattr(sale, "reconciliation", None), "shortage", sale.grand_total_sale) for sale in transactions), Decimal("0")),
			"net": sum((sale.net_sale for sale in transactions), Decimal("0")),
		}

	days_in_month = monthrange(selected_year, selected_month)[1]
	daily_sales = defaultdict(lambda: Decimal("0"))
	daily_orders = defaultdict(set)
	for sale in month_transactions:
		daily_sales[sale.date.day] += sale.sale_total
		daily_orders[sale.date.day].add(sale.invoice_number)
	max_sales = max(daily_sales.values(), default=Decimal("0"))
	max_orders = max((len(order_numbers) for order_numbers in daily_orders.values()), default=0)
	sales_trend = [
		{"day": day, "value": daily_sales[day], "percent": float(daily_sales[day] / max_sales * 100) if max_sales else 0}
		for day in range(1, days_in_month + 1)
	]
	order_trend = [
		{"day": day, "value": len(daily_orders[day]), "percent": (len(daily_orders[day]) / max_orders * 100) if max_orders else 0}
		for day in range(1, days_in_month + 1)
	]

	top_products = defaultdict(lambda: {"name": "", "category": "", "unit": "unit", "quantity": Decimal("0")})
	for sale in month_transactions:
		for item in sale.items.all():
			key = item.product_id_snapshot if item.product_id_snapshot is not None else item.product_id
			row = top_products[key]
			row["name"] = item.product_name_snapshot or (item.product.name if item.product_id else "Historical product")
			row["category"] = item.category_snapshot or (item.product.category.name if item.product_id else "")
			row["unit"] = item.product.unit if item.product_id else "unit"
			row["quantity"] += item.sale_quantity
	top_products = sorted(top_products.values(), key=lambda row: row["quantity"], reverse=True)[:10]

	active_products = list(Product.objects.filter(group=group, active=True).order_by("name"))
	stock = stock_rows(active_products)
	low_stock = [row for row in stock if 0 < row["balance_pieces"] <= row["product"].ctn_size][:8]
	out_of_stock = [row for row in stock if row["balance_pieces"] <= 0][:8]
	recent_invoices = [
		{
			"id": sale.pk,
			"date": sale.date,
			"invoice": sale.invoice_number,
			"route": sale.route_display if sale.route_id or sale.dealer_id else "-",
			"total": sale.sale_total,
			"status": sale.get_status_display(),
		}
		for sale in month_transactions[:8]
	]
	years = set(base_transactions.values_list("date__year", flat=True))
	years.add(today.year)
	return render(request, "dashboard.html", {
		"today": metrics(today_transactions),
		"monthly": metrics(month_transactions),
		"today_date": today,
		"current_month": selected_month,
		"current_year": selected_year,
		"month_options": [(number, date(2000, number, 1).strftime("%B")) for number in range(1, 13)],
		"year_options": sorted(years),
		"sales_trend": sales_trend,
		"order_trend": order_trend,
		"top_products": top_products,
		"active_product_count": len(active_products),
		"in_stock_count": sum(1 for row in stock if row["balance_pieces"] > 0),
		"out_of_stock_count": sum(1 for row in stock if row["balance_pieces"] <= 0),
		"low_stock": low_stock,
		"out_of_stock": out_of_stock,
		"recent_invoices": recent_invoices,
	})


def product_list(request):
	group = get_current_group(request)
	products = Product.objects.filter(group=group)
	context = {"products": products, "categories": Category.objects.filter(group=group, active=True)}
	if request.method == "POST":
		product = Product(
			group=group,
			name=request.POST.get("name", "").strip(),
			category=request.POST.get("category", "").strip(),
			ctn_size=request.POST.get("ctn_size") or 1,
			dealer_price=request.POST.get("dealer_price") or 0,
			trade_price=request.POST.get("trade_price") or 0,
			selling_price=request.POST.get("selling_price") or 0,
			unit=request.POST.get("unit", "unit").strip() or "unit",
		)
		product.category = _category_for_group(group, request.POST.get("category"))
		try:
			product.full_clean()
			product.save()
		except Exception as exc:
			return render(request, "products/list.html", {**context, "error": str(exc)})
		return redirect("product-list")
	return render(request, "products/list.html", context)


def product_setup(request):
	group = get_current_group(request)
	categories = Category.objects.filter(group=group).order_by("name", "id")
	active_categories = categories.filter(active=True)
	query = request.GET.get("q", "").strip()
	category_filter = request.GET.get("category", "").strip()
	status_filter = request.GET.get("status", "").strip()
	category_order = {category_id: index for index, category_id in enumerate(categories.values_list("id", flat=True))}
	products = Product.objects.filter(group=group).order_by("category", "name")
	if query:
		products = products.filter(Q(name__icontains=query) | Q(category__name__icontains=query))
	if category_filter:
		products = products.filter(category__name__iexact=category_filter)
	if status_filter in ("active", "inactive"):
		products = products.filter(active=status_filter == "active")
	products = products.distinct()
	products = sorted(products, key=lambda product: (category_order.get(product.category_id, len(category_order)), product.name.lower()))
	page_obj = Paginator(products, 20).get_page(request.GET.get("page"))
	filter_params = request.GET.copy()
	filter_params.pop("page", None)
	context = {"products": page_obj.object_list, "page_obj": page_obj, "query": query, "category_filter": category_filter, "status_filter": status_filter, "categories": categories, "active_categories": active_categories, "filter_query": filter_params.urlencode(), "editing": None}
	if request.method == "POST":
		action = request.POST.get("action")
		if action in ("toggle", "delete"):
			product = Product.objects.get(pk=request.POST["product_id"], group=group)
			if action == "delete":
				product_name = product.name
				product.delete()
				messages.success(request, f"{product_name} was deleted.")
			else:
				product.active = not product.active
				product.save(update_fields=["active"])
				messages.success(request, f"{product.name} was {'reactivated' if product.active else 'deactivated'}.")
			return redirect("product-setup")
		product = Product(
			group=group,
			name=request.POST.get("name", "").strip(),
			category=request.POST.get("category", "").strip(),
			ctn_size=request.POST.get("ctn_size") or 1,
			dealer_price=request.POST.get("dealer_price") or 0,
			trade_price=request.POST.get("trade_price") or 0,
			foc=request.POST.get("foc") or 0,
			selling_price=request.POST.get("selling_price") or 0,
			reference_dealer_price=request.POST.get("reference_dealer_price") or 0,
			markup_price=request.POST.get("markup_price") or 0,
			unit=request.POST.get("unit", "unit").strip() or "unit",
		)
		product.category = _category_for_group(group, request.POST.get("category"))
		product_id = request.POST.get("product_id")
		if product_id:
			product = Product.objects.get(pk=product_id, group=group)
			for field in ("name", "category", "ctn_size", "unit", "dealer_price", "trade_price", "foc", "selling_price", "reference_dealer_price", "markup_price"):
				value = _category_for_group(group, request.POST.get(field)) if field == "category" else request.POST.get(field)
				setattr(product, field, value if field != "name" else (value or "").strip())
		try:
			product.full_clean()
			product.save()
		except Exception as exc:
			context.update({"editing": product if product.pk else None, "error": str(exc)})
			return render(request, "products/setup.html", context)
		messages.success(request, f"{product.name} was {'updated' if product_id else 'added'} successfully.")
		return redirect("product-setup")
	return render(request, "products/setup.html", context)


def category_management(request):
	group = get_current_group(request)
	categories = Category.objects.filter(group=group).order_by("name", "id")
	context = {"categories": categories, "current_group": group}
	if request.method == "POST":
		action = request.POST.get("action")
		try:
			if action == "create_category":
				category = Category(group=group, name=request.POST.get("category_name", ""))
				category.save()
				messages.success(request, f"{category.name} was created.")
			elif action in ("edit_category", "toggle_category", "delete_category"):
				category = get_object_or_404(Category, pk=request.POST.get("category_id"), group=group)
				if action == "edit_category":
					category.name = request.POST.get("category_name", "")
					category.save()
					messages.success(request, "Category updated.")
				elif action == "toggle_category":
					category.active = not category.active
					category.save(update_fields=["active"])
					messages.success(request, f"{category.name} was {'activated' if category.active else 'deactivated'}.")
				else:
					category.delete()
					messages.success(request, "Category deleted.")
		except Exception as exc:
			context["error"] = str(exc)
			return render(request, "products/category_management.html", context)
		return redirect("category-management")
	return render(request, "products/category_management.html", context)


def product_edit(request, pk):
	group = get_current_group(request)
	product = get_object_or_404(Product, pk=pk, group=group)
	if request.method == "POST":
		post = request.POST
		for field in ("name", "category", "ctn_size", "unit", "dealer_price", "trade_price", "foc", "selling_price", "reference_dealer_price", "markup_price"):
			if field == "unit":
				value = post.get(field, product.unit).strip() or product.unit
			elif field == "category":
				value = _category_for_group(group, post.get(field))
			else:
				value = post.get(field, "").strip() if field == "name" else post.get(field) or 0
			setattr(product, field, value)
		try:
			product.full_clean()
			product.save()
		except Exception as exc:
			return render(request, "products/setup.html", {"products": Product.objects.filter(group=group)[:20], "page_obj": None, "categories": Category.objects.filter(group=group), "active_categories": Category.objects.filter(group=group, active=True), "editing": product, "history": product.price_history.all(), "error": str(exc)})
		messages.success(request, f"{product.name} was updated successfully.")
		return redirect("product-setup")
	return render(request, "products/setup.html", {"products": Product.objects.filter(group=group), "categories": Category.objects.filter(group=group), "active_categories": Category.objects.filter(group=group, active=True), "editing": product, "history": product.price_history.all()})
