from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from products.models import Product

from .forms import GodownStockReceiptForm
from .services import stock_history, stock_rows


def _category_sorted(products):
    category_order = {category: index for index, category in enumerate(Product.CATEGORY_ORDER)}
    return sorted(products, key=lambda product: (category_order.get(product.category, len(category_order)), product.name.lower()))


def godown_stock(request):
    query = request.GET.get("q", "").strip()
    category_filter = request.GET.get("category", "").strip()
    products = Product.objects.filter(active=True)
    if query:
        products = products.filter(Q(name__icontains=query) | Q(category__icontains=query))
    if category_filter in Product.CATEGORY_ORDER:
        products = products.filter(category=category_filter)
    products = _category_sorted(products)
    rows_by_product = {row["product"].pk: row for row in stock_rows(products)}
    grouped_rows = []
    for category in Product.CATEGORY_ORDER:
        category_rows = [rows_by_product[product.pk] for product in products if product.category == category]
        if category_rows:
            grouped_rows.append((category, category_rows))
    return render(
        request,
        "godown_stock/stock_list.html",
        {
            "grouped_rows": grouped_rows,
            "categories": Product.CATEGORY_ORDER,
            "query": query,
            "category_filter": category_filter,
        },
    )


def add_stock(request):
    form = GodownStockReceiptForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        receipt = form.save()
        messages.success(request, f"Stock receipt saved: {receipt.total_pieces} PCS for {receipt.product.name}.")
        return redirect("godown-stock")
    return render(request, "godown_stock/add_stock.html", {"form": form})


def stock_history_view(request, product_id=None):
    product = None
    events = []
    if product_id:
        product = get_object_or_404(Product, pk=product_id)
        events = stock_history(product)
    return render(
        request,
        "godown_stock/stock_history.html",
        {
            "product": product,
            "events": events,
            "products": _category_sorted(Product.objects.filter(active=True)),
        },
    )
