from decimal import Decimal

from django.test import TestCase

from products.models import Product

from .models import Damage


class DamageTests(TestCase):
    def test_damage_value_uses_dealer_price(self):
        product = Product.objects.create(name="Test Product", dealer_price=Decimal("80"))
        damage = Damage.objects.create(date="2026-09-26", product=product, quantity=3)
        self.assertEqual(damage.value, Decimal("240.00"))