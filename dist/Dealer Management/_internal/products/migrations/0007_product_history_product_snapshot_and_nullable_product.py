import django.db.models.deletion
from django.db import migrations, models


def backfill_product_price_history_snapshots(apps, schema_editor):
    ProductPriceHistory = apps.get_model("products", "ProductPriceHistory")

    for history in ProductPriceHistory.objects.select_related("product").iterator():
        product = history.product
        if not product:
            continue
        ProductPriceHistory.objects.filter(pk=history.pk).update(
            product_id_snapshot=product.pk,
            product_name_snapshot=product.name,
            category_snapshot=product.category,
            ctn_size_snapshot=product.ctn_size,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0006_alter_product_ctn_size"),
    ]

    operations = [
        migrations.AddField(
            model_name="productpricehistory",
            name="product_id_snapshot",
            field=models.BigIntegerField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="productpricehistory",
            name="product_name_snapshot",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="productpricehistory",
            name="category_snapshot",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="productpricehistory",
            name="ctn_size_snapshot",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.RunPython(backfill_product_price_history_snapshots, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="productpricehistory",
            name="product",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="price_history",
                to="products.product",
            ),
        ),
    ]
