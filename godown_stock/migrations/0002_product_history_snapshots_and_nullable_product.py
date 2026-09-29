import django.db.models.deletion
from django.db import migrations, models


def backfill_receipt_product_snapshots(apps, schema_editor):
    GodownStockReceipt = apps.get_model("godown_stock", "GodownStockReceipt")

    for receipt in GodownStockReceipt.objects.select_related("product").iterator():
        product = receipt.product
        if not product:
            continue
        GodownStockReceipt.objects.filter(pk=receipt.pk).update(
            product_id_snapshot=product.pk,
            product_name_snapshot=product.name,
            category_snapshot=product.category,
            ctn_size_snapshot=product.ctn_size,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("godown_stock", "0001_initial"),
        ("products", "0007_product_history_product_snapshot_and_nullable_product"),
    ]

    operations = [
        migrations.AddField(
            model_name="godownstockreceipt",
            name="product_id_snapshot",
            field=models.BigIntegerField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="godownstockreceipt",
            name="product_name_snapshot",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="godownstockreceipt",
            name="category_snapshot",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="godownstockreceipt",
            name="ctn_size_snapshot",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.RunPython(backfill_receipt_product_snapshots, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="godownstockreceipt",
            name="product",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="godown_stock_receipts",
                to="products.product",
            ),
        ),
    ]
