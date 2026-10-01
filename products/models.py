from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from dealers.models import Group


class Product(models.Model):
	group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="products")
	category = models.ForeignKey("Category", on_delete=models.PROTECT, related_name="products")
	# Legacy names remain as input aliases for imports and older callers. Categories
	# themselves are database records scoped to a Group.
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
	name = models.CharField(max_length=160)
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

	def __init__(self, *args, **kwargs):
		legacy_category = kwargs.pop("category", None)
		super().__init__(*args, **kwargs)
		if legacy_category is not None:
			if isinstance(legacy_category, Category):
				self.category = legacy_category
			else:
				self._legacy_category_name = str(legacy_category).strip()

	class Meta:
		ordering = ["name"]

	def clean(self):
		errors = {}
		if not self.group_id:
			self.group = Group.default()
		if self.group_id and not self.category_id:
			category_name = getattr(self, "_legacy_category_name", "")
			self.category = Category.objects.filter(group_id=self.group_id, name__iexact=category_name).first()
			if not self.category_id and category_name:
				self.category = Category.objects.create(group_id=self.group_id, name=category_name)
			if not self.category_id:
				self.category = Category.objects.filter(group_id=self.group_id).first()
		if not self.name.strip():
			errors["name"] = "Product name is required."
		if not self.category_id:
			errors["category"] = "Select a valid category for this group."
		elif self.category.group_id != self.group_id:
			errors["category"] = "Category must belong to the selected group."
		if not str(self.unit or "").strip():
			errors["unit"] = "Unit is required."
		for field in ("dealer_price", "trade_price", "foc", "selling_price", "reference_dealer_price", "markup_price"):
			if getattr(self, field) < 0:
				errors[field] = "This value cannot be negative."
		duplicate = Product.objects.filter(group=self.group, name__iexact=self.name.strip()).exclude(pk=self.pk).exists()
		if duplicate:
			errors["name"] = "A product with this name already exists."
		if errors:
			raise ValidationError(errors)

	def __str__(self):
		return self.name

	def save(self, *args, **kwargs):
		if not self.group_id:
			self.group = Group.default()
		if self.group_id and not self.category_id:
			category_name = getattr(self, "_legacy_category_name", "")
			self.category = Category.objects.filter(group_id=self.group_id, name__iexact=category_name).first()
			if not self.category_id and category_name:
				self.category = Category.objects.create(group_id=self.group_id, name=category_name)
			if not self.category_id:
				self.category = Category.objects.filter(group_id=self.group_id).first()
		self.unit = str(self.unit or "unit").strip() or "unit"
		for field in ("dealer_price", "trade_price", "foc", "selling_price", "reference_dealer_price", "markup_price"):
			setattr(self, field, Decimal(str(getattr(self, field) or 0)))
		self.ctn_size = int(self.ctn_size or 1)
		self.clean()
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


class Category(models.Model):
	group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="categories")
	name = models.CharField(max_length=80)
	active = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["name", "id"]
		constraints = [models.UniqueConstraint(Lower("name"), "group", name="unique_group_category_name_ci")]

	def clean(self):
		self.name = self.name.strip()
		if not self.name:
			raise ValidationError({"name": "Category name is required."})
		if Category.objects.filter(group=self.group, name__iexact=self.name).exclude(pk=self.pk).exists():
			raise ValidationError({"name": "A category with this name already exists in this group."})

	def save(self, *args, **kwargs):
		self.full_clean()
		return super().save(*args, **kwargs)

	def __str__(self):
		return self.name


class ProductPriceHistory(models.Model):
	group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="price_history")
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
		if not self.group_id and self.product_id:
			self.group = self.product.group
		if self._state.adding and self.product_id:
			product = self.product
			self.product_id_snapshot = product.pk
			self.product_name_snapshot = product.name
			self.category_snapshot = product.category.name
			self.ctn_size_snapshot = product.ctn_size
		return super().save(*args, **kwargs)
