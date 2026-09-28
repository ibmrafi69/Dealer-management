from django.db import migrations


def normalize_categories(apps, schema_editor):
    Product = apps.get_model("products", "Product")
    aliases = {"Mlk": "Milk", "milk": "Milk", "wefr": "Wefr", "OIL": "Oil"}
    blank_by_name = {
        "Red Cow 200gm": "Milk",
        "Cremo(80gm)": "Bisct",
        "Digestive Chocolet(135gm)": "Bisct",
        "Revoli Butter Cookis 150g": "Bisct",
        "Revoli Coconut Crunch 145g": "Bisct",
        "Revoli Vanila Chocochips 150g": "Bisct",
        "Revoli White Chocolate  145g": "Bisct",
        "Saltish(73gm)": "Bisct",
        "Chicken Curry Masala 100gm": "Msala",
    }
    for product in Product.objects.all():
        category = blank_by_name.get(product.name, aliases.get(product.category, product.category))
        if category:
            Product.objects.filter(pk=product.pk).update(category=category)


class Migration(migrations.Migration):
    dependencies = [("products", "0004_alter_product_category")]
    operations = [migrations.RunPython(normalize_categories, migrations.RunPython.noop)]