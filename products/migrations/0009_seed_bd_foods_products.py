from decimal import Decimal

from django.db import migrations


BD_FOODS_PRODUCTS = (
    ("Potato crackers 15gm", "Ckrs", 80, "single", "600", "630"),
    ("BD Chanachur 200 gm", "Ndls", 26, "single", "591", "630"),
    ("BD Jhal Chanachur 22 gm", "Ndls", 288, "single", "181", "192"),
    ("BD Jhal Chanachur 150 gm", "Ndls", 72, "single", "451", "480"),
    ("BD Jhal Chanachur 300 gm", "Ndls", 24, "single", "451", "480"),
    ("BD BBQ Chanachur 150 gm", "Ndls", 60, "single", "449", "480"),
    ("BD BBQ Chanachur 300 gm", "Ndls", 24, "single", "451", "480"),
    ("BD Lacha Semai 200 gm", "Ndls", 50, "pcs", "1839.5", "39"),
    ("BD Tamarind Chutney", "Wefr", 432, "dozen", "1584", "47"),
    ("BD Olive Chutney", "Wefr", 432, "dozen", "1584", "47"),
    ("BD Hot Tomato Chutney", "Wefr", 780, "dozen", "1608", "26"),
    ("BD Toast Biscuit 285 gm", "Bisct", 12, "pkt", "474.6", "500"),
    ("Butter Toast", "Bisct", 12, "pkt", "577", "612"),
    ("BD Double Toast Biscuit", "Bisct", 60, "pcs", "240", "255"),
    ("Turmeric Powder 100 gm", "Msala", 48, "pcs", "2695", "60"),
    ("Chili Powder 100 gm", "Msala", 48, "pcs", "2695", "60"),
    ("Mangobar 14 gm 24 box x 30 bar", "Wefr", 720, "box", "5300", "250"),
    ("TOP C", "Wefr", 240, "dozen", "1584", "84"),
    ("Happy Cow 200/500 Ndls", "Ndls", 1, "unit", "0", "0"),
)


def seed_bd_foods(apps, schema_editor):
    Group = apps.get_model("dealers", "Group")
    Product = apps.get_model("products", "Product")
    group, _ = Group.objects.get_or_create(name="BD Foods", defaults={"active": True})
    for name, category, ctn_size, unit, dealer_price, selling_price in BD_FOODS_PRODUCTS:
        Product.objects.get_or_create(
            group=group,
            name=name,
            defaults={
                "category": category,
                "ctn_size": ctn_size,
                "unit": unit,
                "dealer_price": Decimal(dealer_price),
                "trade_price": Decimal("0"),
                "foc": Decimal("0"),
                "selling_price": Decimal(selling_price),
                "reference_dealer_price": Decimal("0"),
                "markup_price": Decimal("0"),
                "active": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("dealers", "0005_group_alter_dealer_code_alter_route_route_name_and_more"),
        ("products", "0008_product_group_productpricehistory_group"),
    ]

    operations = [migrations.RunPython(seed_bd_foods, migrations.RunPython.noop)]
