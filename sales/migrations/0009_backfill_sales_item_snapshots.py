from django.db import migrations


def backfill_sales_item_snapshots(apps, schema_editor):
    SalesItem = apps.get_model("sales", "SalesItem")

    for item in SalesItem.objects.select_related("product").all():
        # Snapshot fields were introduced after the original sales records.
        # A non-empty name marks a line already created with the new workflow;
        # those values must never be replaced by current Product Setup values.
        if item.product_name_snapshot:
            continue

        product = item.product
        item.product_name_snapshot = product.name
        item.category_snapshot = product.category
        item.ctn_size_snapshot = product.ctn_size
        item.dealer_price_snapshot = product.dealer_price
        item.trade_price_snapshot = product.trade_price
        item.foc_snapshot = product.foc
        # unit_price is the historically stored line price, so it is the
        # best source for old invoices and must take precedence.
        item.sale_price_snapshot = item.unit_price or product.selling_price or product.trade_price
        item.save(
            update_fields=[
                "product_name_snapshot",
                "category_snapshot",
                "ctn_size_snapshot",
                "dealer_price_snapshot",
                "trade_price_snapshot",
                "foc_snapshot",
                "sale_price_snapshot",
            ]
        )


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0008_backfill_history_snapshots"),
        ("products", "0005_normalize_product_categories"),
    ]

    operations = [migrations.RunPython(backfill_sales_item_snapshots, migrations.RunPython.noop)]
