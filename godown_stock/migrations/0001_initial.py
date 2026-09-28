import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("products", "0006_alter_product_ctn_size"),
    ]

    operations = [
        migrations.CreateModel(
            name="GodownStockReceipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("received_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("received_ctn", models.PositiveIntegerField(default=0)),
                ("received_pcs", models.PositiveIntegerField(default=0)),
                ("total_pieces", models.PositiveIntegerField(editable=False)),
                ("reference", models.CharField(blank=True, help_text="Company, challan, or reference number", max_length=160)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="godown_stock_receipts", to="products.product")),
            ],
            options={"ordering": ["received_at", "created_at", "pk"]},
        ),
    ]
