from django.core.management.base import BaseCommand

from products.models import Product


class Command(BaseCommand):
    help = "Normalize legacy workbook category values to the canonical Product choices."

    LEGACY_ALIASES = {"Mlk": Product.MILK, "milk": Product.MILK, "wefr": Product.WEFR, "Wefr": Product.WEFR, "OIL": Product.OIL}
    BLANK_BY_NAME = {
        "Red Cow 200gm": Product.MILK,
        "Cremo(80gm)": Product.BISCT,
        "Digestive Chocolet(135gm)": Product.BISCT,
        "Revoli Butter Cookis 150g": Product.BISCT,
        "Revoli Coconut Crunch 145g": Product.BISCT,
        "Revoli Vanila Chocochips 150g": Product.BISCT,
        "Revoli White Chocolate  145g": Product.BISCT,
        "Saltish(73gm)": Product.BISCT,
        "Chicken Curry Masala 100gm": Product.MSALA,
    }

    def handle(self, *args, **options):
        changed = 0
        for product in Product.objects.all():
            category = self.LEGACY_ALIASES.get(product.category.name, product.category.name)
            category = self.BLANK_BY_NAME.get(product.name, category)
            if category != product.category.name:
                category_obj, _ = product.group.categories.get_or_create(name=category)
                Product.objects.filter(pk=product.pk).update(category_id=category_obj.pk)
                changed += 1
        self.stdout.write(self.style.SUCCESS(f"Normalized {changed} product categories."))