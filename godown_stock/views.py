from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from products.models import Category, Product
from dealers.context import get_current_group

from .forms import GodownStockReceiptForm
from .services import stock_history, stock_rows


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
    form = GodownStockReceiptForm(request.POST or None, group=group)
    if request.method == "POST" and form.is_valid():
        receipt = form.save()
        messages.success(request, f"Stock receipt saved: {receipt.total_pieces} PCS for {receipt.product.name}.")
        return redirect("godown-stock")
    return render(request, "godown_stock/add_stock.html", {"form": form})


def stock_history_view(request, product_id=None):
    group = get_current_group(request)
    product = None
    events = []
    if product_id:
        product = get_object_or_404(Product, pk=product_id, group=group)
        events = stock_history(product)
    return render(
        request,
        "godown_stock/stock_history.html",
        {
            "product": product,
            "events": events,
            "products": _category_sorted(Product.objects.filter(group=group, active=True)),
        },
    )
