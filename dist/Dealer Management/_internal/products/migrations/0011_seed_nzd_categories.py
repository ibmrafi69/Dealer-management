from django.db import migrations


NZD_CATEGORIES = ("Milk", "Ghee", "Ndls", "Ckrs", "Wefr", "Bisct", "Msala", "Rice", "Atta", "Suji", "Oil")


def seed_nzd_categories(apps, schema_editor):
    Group = apps.get_model("dealers", "Group")
    Category = apps.get_model("products", "Category")
    group = Group.objects.filter(name="New Zealand Dairy").first()
    if group:
        for name in NZD_CATEGORIES:
            Category.objects.get_or_create(group_id=group.pk, name=name, defaults={"active": True})


class Migration(migrations.Migration):
    dependencies = [("products", "0010_category_product_category")]
    operations = [migrations.RunPython(seed_nzd_categories, migrations.RunPython.noop)]