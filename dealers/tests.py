from django.test import TestCase

from .models import Dealer


class DealerTests(TestCase):
    def test_dealer_can_be_created(self):
        dealer = Dealer.objects.create(name="Central Store", code="CENTRAL")
        self.assertEqual(str(dealer), "Central Store (CENTRAL)")