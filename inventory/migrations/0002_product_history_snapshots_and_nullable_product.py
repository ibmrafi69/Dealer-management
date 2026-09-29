from decimal import Decimal, ROUND_HALF_UP

import django.db.models.deletion
from django.db import migrations, models


def backfill_inventory_product_snapshots(apps, schema_editor):
    Damage = apps.get_model("inventory", "Damage")
    SalesItem = apps.get_model("sales", "SalesItem")
    StockTransaction = apps.get_model("inventory", "StockTransaction")

    for damage in Damage.objects.select_related("product").iterator():
        product = damage.product
        if not product:
            continue

        unit_price = product.dealer_price
        if damage.related_transaction_id:
            item = SalesItem.objects.filter(
                transaction_id=damage.related_transaction_id,
                product_id_snapshot=product.pk,
            ).only("sale_price_snapshot").first()
            if item:
                unit_price = item.sale_price_snapshot
        elif damage.quantity:
            unit_price = (damage.value / damage.quantity).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        Damage.objects.filter(pk=damage.pk).update(
            product_id_snapshot=product.pk,
            product_name_snapshot=product.name,
            category_snapshot=product.category,
            ctn_size_snapshot=product.ctn_size,
            unit_price_snapshot=unit_price,
        )

    for transaction in StockTransaction.objects.select_related("product").iterator():
        product = transaction.product
        if not product:
            continue
        StockTransaction.objects.filter(pk=transaction.pk).update(
            product_id_snapshot=product.pk,
            product_name_snapshot=product.name,
            category_snapshot=product.category,
            ctn_size_snapshot=product.ctn_size,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0001_initial"),
        ("products", "0007_product_history_product_snapshot_and_nullable_product"),
        ("sales", "0013_salesitem_product_snapshot_and_nullable_product"),
    ]

    operations = [
        migrations.AddField(
            model_name="damage",
            name="product_id_snapshot",
            field=models.BigIntegerField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="damage",
            name="product_name_snapshot",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="damage",
            name="category_snapshot",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="damage",
            name="ctn_size_snapshot",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="damage",
            name="unit_price_snapshot",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="stocktransaction",
            name="product_id_snapshot",
            field=models.BigIntegerField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="stocktransaction",
            name="product_name_snapshot",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="stocktransaction",
            name="category_snapshot",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="stocktransaction",
            name="ctn_size_snapshot",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.RunPython(backfill_inventory_product_snapshots, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="damage",
            name="product",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="damages",
                to="products.product",
            ),
        ),
        migrations.AlterField(
            model_name="stocktransaction",
            name="product",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="stock_transactions",
                to="products.product",
            ),
        ),
    ]
