from datetime import date

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import redirect, render

from dealers.models import Dealer
from sales.models import SalesTransaction

from .models import Product


def home(request):
	return render(request, "home.html")


def dashboard(request):
	today = date.today()
	today_sales = SalesTransaction.objects.filter(date=today).prefetch_related("items", "damages")
	month_sales = SalesTransaction.objects.filter(date__year=today.year, date__month=today.month).prefetch_related("items", "damages")
	def metrics(transactions):
		return {
			"sales": sum((sale.sale_total for sale in transactions), 0),
			"orders": transactions.count(),
			"returns": sum((sale.return_total for sale in transactions), 0),
			"damage": sum((sale.damage_total for sale in transactions), 0),
			"discount": sum((sale.total_discount + sale.free_product_total for sale in transactions), 0),
			"net": sum((sale.net_sale for sale in transactions), 0),
		}
	return render(request, "dashboard.html", {"today": metrics(today_sales), "monthly": metrics(month_sales), "today_date": today})


def product_list(request):
	products = Product.objects.all()
	context = {"products": products, "categories": Product.CATEGORY_ORDER}
	if request.method == "POST":
		product = Product(
			name=request.POST.get("name", "").strip(),
			category=request.POST.get("category", "").strip(),
			ctn_size=request.POST.get("ctn_size") or 1,
			dealer_price=request.POST.get("dealer_price") or 0,
			trade_price=request.POST.get("trade_price") or 0,
			selling_price=request.POST.get("selling_price") or 0,
			unit=request.POST.get("unit", "unit").strip() or "unit",
		)
		try:
			product.full_clean()
			product.save()
		except Exception as exc:
			return render(request, "products/list.html", {**context, "error": str(exc)})
		return redirect("product-list")
	return render(request, "products/list.html", context)


def product_setup(request):
	query = request.GET.get("q", "").strip()
	category_filter = request.GET.get("category", "").strip()
	status_filter = request.GET.get("status", "").strip()
	category_order = {category: index for index, category in enumerate(Product.CATEGORY_ORDER)}
	products = Product.objects.all().order_by("category", "name")
	if query:
		products = products.filter(Q(name__icontains=query) | Q(category__icontains=query))
	if category_filter:
		products = products.filter(category__iexact=category_filter)
	if status_filter in ("active", "inactive"):
		products = products.filter(active=status_filter == "active")
	products = products.distinct()
	products = sorted(products, key=lambda product: (category_order.get(product.category, len(category_order)), product.name.lower()))
	all_categories = Product.CATEGORY_ORDER
	page_obj = Paginator(products, 20).get_page(request.GET.get("page"))
	filter_params = request.GET.copy()
	filter_params.pop("page", None)
	referenced_ids = set(Product.objects.filter(Q(sales_items__isnull=False) | Q(damages__isnull=False) | Q(stock_transactions__isnull=False) | Q(godown_stock_receipts__isnull=False)).values_list("id", flat=True))
	context = {"products": page_obj.object_list, "page_obj": page_obj, "query": query, "category_filter": category_filter, "status_filter": status_filter, "categories": all_categories, "filter_query": filter_params.urlencode(), "referenced_ids": referenced_ids, "editing": None}
	if request.method == "POST":
		action = request.POST.get("action")
		if action in ("toggle", "delete"):
			product = Product.objects.get(pk=request.POST["product_id"])
			has_history = product.sales_items.exists() or product.damages.exists() or product.stock_transactions.exists() or product.godown_stock_receipts.exists()
			if action == "delete" and not has_history:
				product.price_history.all().delete()
				product.delete()
				messages.success(request, f"{product.name} was deleted.")
			elif action == "delete" and has_history:
				product.active = False
				product.save(update_fields=["active"])
				messages.warning(request, f"{product.name} has historical transactions and was deactivated instead of deleted.")
			else:
				product.active = not product.active
				product.save(update_fields=["active"])
				messages.success(request, f"{product.name} was {'reactivated' if product.active else 'deactivated'}.")
			return redirect("product-setup")
		product = Product(
			name=request.POST.get("name", "").strip(),
			category=request.POST.get("category", "").strip(),
			ctn_size=request.POST.get("ctn_size") or 1,
			dealer_price=request.POST.get("dealer_price") or 0,
			trade_price=request.POST.get("trade_price") or 0,
			foc=request.POST.get("foc") or 0,
			selling_price=request.POST.get("selling_price") or 0,
			reference_dealer_price=request.POST.get("reference_dealer_price") or 0,
			markup_price=request.POST.get("markup_price") or 0,
			unit="unit",
		)
		product_id = request.POST.get("product_id")
		if product_id:
			product = Product.objects.get(pk=product_id)
			for field in ("name", "category", "ctn_size", "dealer_price", "trade_price", "foc", "selling_price", "reference_dealer_price", "markup_price"):
				setattr(product, field, request.POST.get(field) if field not in ("name", "category") else request.POST.get(field, "").strip())
		try:
			product.full_clean()
			product.save()
		except Exception as exc:
			context.update({"editing": product, "error": str(exc)})
			return render(request, "products/setup.html", context)
		messages.success(request, f"{product.name} was {'updated' if product_id else 'added'} successfully.")
		return redirect("product-setup")
	return render(request, "products/setup.html", context)


def product_edit(request, pk):
	product = Product.objects.get(pk=pk)
	if request.method == "POST":
		post = request.POST
		for field in ("name", "category", "ctn_size", "dealer_price", "trade_price", "foc", "selling_price", "reference_dealer_price", "markup_price"):
			setattr(product, field, post.get(field, "").strip() if field in ("name", "category") else post.get(field) or 0)
		try:
			product.full_clean()
			product.save()
		except Exception as exc:
			return render(request, "products/setup.html", {"products": Product.objects.all()[:20], "page_obj": None, "categories": Product.CATEGORY_ORDER, "editing": product, "history": product.price_history.all(), "error": str(exc)})
		messages.success(request, f"{product.name} was updated successfully.")
		return redirect("product-setup")
	return render(request, "products/setup.html", {"products": Product.objects.all(), "categories": Product.CATEGORY_ORDER, "editing": product, "history": product.price_history.all()})
