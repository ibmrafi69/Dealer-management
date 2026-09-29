from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models


class Product(models.Model):
	MILK = "Milk"
	GHEE = "Ghee"
	NDLS = "Ndls"
	CKRS = "Ckrs"
	WEFR = "Wefr"
	BISCT = "Bisct"
	MSALA = "Msala"
	RICE = "Rice"
	ATTA = "Atta"
	SUJI = "Suji"
	OIL = "Oil"
	CATEGORY_CHOICES = ((MILK, "Milk"), (GHEE, "Ghee"), (NDLS, "Ndls"), (CKRS, "Ckrs"), (WEFR, "Wefr"), (BISCT, "Bisct"), (MSALA, "Msala"), (RICE, "Rice"), (ATTA, "Atta"), (SUJI, "Suji"), (OIL, "Oil"))
	CATEGORY_ORDER = [choice[0] for choice in CATEGORY_CHOICES]
	name = models.CharField(max_length=160)
	category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
	# This has always been the product-specific number of pieces in one carton.
	# Keep the field name for compatibility with saved sales snapshots, but expose
	# its business meaning consistently in Product Setup and Godown Stock.
	ctn_size = models.PositiveIntegerField("Pieces per CTN", default=1)
	dealer_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	trade_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	foc = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	selling_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	reference_dealer_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	markup_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	unit = models.CharField(max_length=30, default="unit")
	active = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["name"]

	def clean(self):
		errors = {}
		if not self.name.strip():
			errors["name"] = "Product name is required."
		if self.category not in dict(self.CATEGORY_CHOICES):
			errors["category"] = "Select a valid category."
		for field in ("dealer_price", "trade_price", "foc", "selling_price", "reference_dealer_price", "markup_price"):
			if getattr(self, field) < 0:
				errors[field] = "This value cannot be negative."
		duplicate = Product.objects.filter(name__iexact=self.name.strip()).exclude(pk=self.pk).exists()
		if duplicate:
			errors["name"] = "A product with this name already exists."
		if errors:
			raise ValidationError(errors)

	def __str__(self):
		return self.name

	def save(self, *args, **kwargs):
		for field in ("dealer_price", "trade_price", "foc", "selling_price", "reference_dealer_price", "markup_price"):
			setattr(self, field, Decimal(str(getattr(self, field) or 0)))
		self.ctn_size = int(self.ctn_size or 1)
		previous = Product.objects.get(pk=self.pk) if self.pk else None
		super().save(*args, **kwargs)
		if previous:
			changes = (
				("DEALER_PRICE", previous.dealer_price, self.dealer_price),
				("TRADE_PRICE", previous.trade_price, self.trade_price),
				("SALE_PRICE", previous.selling_price, self.selling_price),
			)
			for price_type, old_price, new_price in changes:
				if old_price != new_price:
					ProductPriceHistory.objects.create(product=self, price_type=price_type, old_price=old_price, new_price=new_price)

	@property
	def effective_sale_price(self):
		return self.selling_price or self.trade_price

	@property
	def pieces_per_ctn(self):
		"""Readable inventory name for the existing carton-size field."""
		return self.ctn_size


class ProductPriceHistory(models.Model):
	DEALER_PRICE = "DEALER_PRICE"
	TRADE_PRICE = "TRADE_PRICE"
	SALE_PRICE = "SALE_PRICE"
	PRICE_TYPES = ((DEALER_PRICE, "Dealer price"), (TRADE_PRICE, "Trade price"), (SALE_PRICE, "Sale price"))
	product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name="price_history")
	product_id_snapshot = models.BigIntegerField(null=True, blank=True, editable=False)
	product_name_snapshot = models.CharField(max_length=160, blank=True)
	category_snapshot = models.CharField(max_length=20, blank=True)
	ctn_size_snapshot = models.PositiveIntegerField(default=1)
	old_price = models.DecimalField(max_digits=12, decimal_places=2)
	new_price = models.DecimalField(max_digits=12, decimal_places=2)
	price_type = models.CharField(max_length=20, choices=PRICE_TYPES)
	effective_at = models.DateTimeField(auto_now_add=True)

	def save(self, *args, **kwargs):
		if self._state.adding and self.product_id:
			product = self.product
			self.product_id_snapshot = product.pk
			self.product_name_snapshot = product.name
			self.category_snapshot = product.category
			self.ctn_size_snapshot = product.ctn_size
		return super().save(*args, **kwargs)
