import django.db.models.deletion
from django.db import migrations, models


def backfill_sales_item_product_snapshots(apps, schema_editor):
    SalesItem = apps.get_model("sales", "SalesItem")

    for item in SalesItem.objects.select_related("product").iterator():
        product = item.product
        if not product:
            continue

        updates = {"product_id_snapshot": product.pk}
        if not item.product_name_snapshot:
            updates.update(
                product_name_snapshot=product.name,
                category_snapshot=product.category,
                ctn_size_snapshot=product.ctn_size,
                dealer_price_snapshot=product.dealer_price,
                trade_price_snapshot=product.trade_price,
                foc_snapshot=product.foc,
                sale_price_snapshot=item.unit_price or product.selling_price or product.trade_price,
            )
        SalesItem.objects.filter(pk=item.pk).update(**updates)


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0007_product_history_product_snapshot_and_nullable_product"),
        ("sales", "0012_salestransaction_status_updated_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="salesitem",
            name="product_id_snapshot",
            field=models.BigIntegerField(blank=True, editable=False, null=True),
        ),
        migrations.RunPython(backfill_sales_item_product_snapshots, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="salesitem",
            name="product",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="sales_items",
                to="products.product",
            ),
        ),
    ]
