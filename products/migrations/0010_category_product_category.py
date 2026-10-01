from django.db import migrations, models
import django.db.models.deletion
from django.db.models.functions import Lower


def migrate_product_categories(apps, schema_editor):
    Category = apps.get_model("products", "Category")
    Product = apps.get_model("products", "Product")
    for product in Product.objects.select_related("group").all().iterator():
        category, _ = Category.objects.get_or_create(
            group_id=product.group_id,
            name=product.category,
            defaults={"active": True},
        )
        Product.objects.filter(pk=product.pk).update(category_new_id=category.pk)


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0009_seed_bd_foods_products"),
    ]

    operations = [
        migrations.CreateModel(
            name="Category",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="categories", to="dealers.group")),
            ],
            options={"ordering": ["name", "id"]},
        ),
        migrations.AddConstraint(
            model_name="category",
            constraint=models.UniqueConstraint(Lower("name"), models.F("group"), name="unique_group_category_name_ci"),
        ),
        migrations.AddField(
            model_name="product",
            name="category_new",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="new_products", to="products.category"),
        ),
        migrations.RunPython(migrate_product_categories, migrations.RunPython.noop),
        migrations.RemoveField(model_name="product", name="category"),
        migrations.RenameField(model_name="product", old_name="category_new", new_name="category"),
        migrations.AlterField(
            model_name="product",
            name="category",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="products", to="products.category"),
        ),
    ]