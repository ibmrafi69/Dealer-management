from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0005_normalize_product_categories"),
    ]

    operations = [
        migrations.AlterField(
            model_name="product",
            name="ctn_size",
            field=models.PositiveIntegerField(default=1, verbose_name="Pieces per CTN"),
        ),
    ]
