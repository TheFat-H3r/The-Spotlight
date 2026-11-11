from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import F, Q

from marketplace.models import unique_slug


# ---------------------------------------------------------------------------
# Product (a listing sold by a store)
# ---------------------------------------------------------------------------
class ProductQuerySet(models.QuerySet):
    def public(self):
        """Products that customers are allowed to see."""
        return self.filter(
            status=Product.Status.ACTIVE,
            store__status="active",
            store__vendor__status="active",
            store__vendor__user__is_active=True,
            category__is_active=True,
        )

    def in_stock(self):
        """Products with at least one active variant that can be bought."""
        return self.filter(
            Q(variants__is_active=True),
            Q(variants__inventory__track_stock=False)
            | Q(variants__inventory__quantity__gt=F("variants__inventory__reserved_quantity")),
        ).distinct()


class Product(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft (not public)"
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived by vendor"
        HIDDEN = "hidden", "Hidden by admin"

    class Condition(models.TextChoices):
        NEW = "new", "New"
        LIKE_NEW = "like_new", "Like new"
        USED = "used", "Used"
        HANDMADE = "handmade", "Handmade"

    store = models.ForeignKey(
        "marketplace.Store",
        on_delete=models.CASCADE,
        related_name="products",
    )
    category = models.ForeignKey(
        "marketplace.Category",
        on_delete=models.PROTECT,
        related_name="products",
        limit_choices_to=Q(kind__in=["product", "both"]),
    )

    # Identity
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, unique=True, blank=True)
    short_description = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    condition = models.CharField(
        max_length=10, choices=Condition.choices, default=Condition.NEW
    )
    tags = models.JSONField(
        default=list, blank=True, help_text='e.g. ["vegan", "spicy"]. Used by search.'
    )

    # Pricing (variants may override `price`)
    price = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    compare_at_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Original price. Shown struck through when higher than `price`.",
    )

    # Visibility and moderation
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    is_featured = models.BooleanField(default=False)

    # Denormalised stats (rating is updated by the reviews app)
    rating_average = models.DecimalField(max_digits=3, decimal_places=2, default=0)  # type: ignore
    rating_count = models.PositiveIntegerField(default=0)
    sold_count = models.PositiveIntegerField(default=0)
    view_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ["-is_featured", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["store", "name"], name="unique_product_name_per_store"
            ),
            # On Django < 5.1 use `check=` instead of `condition=`.
            models.CheckConstraint(
                condition=Q(price__gte=0), name="product_price_non_negative"
            ),
        ]
        indexes = [
            models.Index(fields=["status", "is_featured"]),
            models.Index(fields=["category", "status"]),
            models.Index(fields=["store", "status"]),
            models.Index(fields=["price"]),
        ]

    def __str__(self):
        return self.name

    # -- helpers ------------------------------------------------------------
    @property
    def is_public(self):
        store = self.store
        return (
            self.status == self.Status.ACTIVE
            and store.status == "active"
            and store.vendor.status == "active"
            and store.vendor.user.is_active
            and self.category.is_active
        )

    @property
    def is_on_sale(self):
        return self.compare_at_price is not None and self.compare_at_price > self.price

    @property
    def discount_percent(self):
        if not self.is_on_sale:
            return 0
        return int((1 - self.price / self.compare_at_price) * 100)  # type: ignore

    @property
    def has_variants(self):
        """True when the vendor created options beyond the automatic default."""
        return self.variants.filter(is_default=False).exists() # type: ignore

    @property
    def default_variant(self):
        return self.variants.filter(is_default=True).first() # type: ignore

    @property
    def primary_image(self):
        return self.images.filter(is_primary=True).first() or self.images.first() # type: ignore

    # -- validation ---------------------------------------------------------
    def clean(self):
        errors = {}
        if self.category_id and self.category.kind == "service":  # type: ignore
            errors["category"] = "Pick a product category, not a service-only one."
        if self.store_id and self.store.store_type == "services":  # type: ignore
            errors["store"] = "This store is set up for services only."
        if self.compare_at_price is not None and self.compare_at_price <= self.price:
            errors["compare_at_price"] = "Must be higher than the selling price."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Product, self.name, self, max_length=160)
        creating = self._state.adding
        super().save(*args, **kwargs)
        # Every product always has one default variant, so carts and orders
        # can always point at a Variant (and therefore its Inventory).
        if creating:
            Variant.objects.create(product=self, name="Default", is_default=True)


# ---------------------------------------------------------------------------
# Variant (a purchasable option: size, flavour, colour... or the default one)
# ---------------------------------------------------------------------------
class Variant(models.Model):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="variants"
    )
    name = models.CharField(
        max_length=100, help_text='e.g. "Large / Red". "Default" for simple products.'
    )
    sku = models.CharField(max_length=50, blank=True)
    attributes = models.JSONField(
        default=dict,
        blank=True,
        help_text='e.g. {"size": "L", "colour": "Red"}. Used for filtering.',
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Leave empty to use the product price.",
    )
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_default", "display_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "name"], name="unique_variant_name_per_product"
            ),
            models.UniqueConstraint(
                fields=["product"],
                condition=Q(is_default=True),
                name="one_default_variant_per_product",
            ),
            models.UniqueConstraint(
                fields=["sku"], condition=~Q(sku=""), name="unique_variant_sku"
            ),
        ]

    def __str__(self):
        if self.is_default:
            return self.product.name
        return f"{self.product.name} — {self.name}"

    @property
    def effective_price(self):
        return self.price if self.price is not None else self.product.price

    def save(self, *args, **kwargs):
        creating = self._state.adding
        super().save(*args, **kwargs)
        if creating:
            Inventory.objects.get_or_create(variant=self)


# ---------------------------------------------------------------------------
# Inventory (stock level for one variant)
# ---------------------------------------------------------------------------
class Inventory(models.Model):
    variant = models.OneToOneField(
        Variant, on_delete=models.CASCADE, related_name="inventory"
    )
    track_stock = models.BooleanField(
        default=True,
        help_text="Turn off for made-to-order items that are never 'out of stock'.",
    )
    quantity = models.PositiveIntegerField(default=0, help_text="Units on hand.")
    reserved_quantity = models.PositiveIntegerField(
        default=0, help_text="Units held by pending orders, not yet handed over."
    )
    low_stock_threshold = models.PositiveIntegerField(
        default=3, help_text="Vendor is warned when available stock drops to this."
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "inventory"
        constraints = [
            models.CheckConstraint(
                condition=Q(reserved_quantity__lte=F("quantity")),
                name="inventory_reserved_lte_quantity",
            )
        ]

    def __str__(self):
        return f"{self.variant}: {self.available} available"

    # -- read helpers -------------------------------------------------------
    @property
    def available(self):
        """Units a customer can still order."""
        return max(self.quantity - self.reserved_quantity, 0)

    @property
    def is_in_stock(self):
        return (not self.track_stock) or self.available > 0

    @property
    def is_low_stock(self):
        return self.track_stock and 0 < self.available <= self.low_stock_threshold

    def can_fulfil(self, qty):
        return (not self.track_stock) or self.available >= qty

    # -- safe stock changes (row-locked so concurrent orders can't oversell) -
    def _locked(self):
        return Inventory.objects.select_for_update().get(pk=self.pk)

    def _sync(self, locked):
        self.quantity = locked.quantity
        self.reserved_quantity = locked.reserved_quantity

    def adjust(self, delta):
        """Vendor stock update: add (+) or remove (-) units on hand."""
        with transaction.atomic():
            inv = self._locked()
            new_qty = inv.quantity + delta
            if new_qty < inv.reserved_quantity:
                raise ValidationError(
                    "Stock cannot drop below the units reserved by open orders."
                )
            inv.quantity = new_qty
            inv.save(update_fields=["quantity", "updated_at"])
            self._sync(inv)

    def reserve(self, qty):
        """Hold units for a new order. Raises if there isn't enough stock."""
        if not self.track_stock:
            return
        with transaction.atomic():
            inv = self._locked()
            if inv.quantity - inv.reserved_quantity < qty:
                raise ValidationError(f"Only {inv.available} left in stock.")
            inv.reserved_quantity += qty
            inv.save(update_fields=["reserved_quantity", "updated_at"])
            self._sync(inv)

    def release(self, qty):
        """Give reserved units back (order cancelled or rejected)."""
        if not self.track_stock:
            return
        with transaction.atomic():
            inv = self._locked()
            inv.reserved_quantity = max(inv.reserved_quantity - qty, 0)
            inv.save(update_fields=["reserved_quantity", "updated_at"])
            self._sync(inv)

    def deduct(self, qty):
        """Order completed: units leave the shelf and the reservation ends."""
        if not self.track_stock:
            return
        with transaction.atomic():
            inv = self._locked()
            inv.reserved_quantity = max(inv.reserved_quantity - qty, 0)
            inv.quantity = max(inv.quantity - qty, 0)
            inv.save(update_fields=["quantity", "reserved_quantity", "updated_at"])
            self._sync(inv)


# ---------------------------------------------------------------------------
# ProductImage
# ---------------------------------------------------------------------------
class ProductImage(models.Model):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="images"
    )
    variant = models.ForeignKey(
        Variant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="images",
        help_text="Optional: show this image when the variant is selected.",
    )
    image = models.ImageField(upload_to="products/")
    alt_text = models.CharField(max_length=150, blank=True)
    is_primary = models.BooleanField(default=False)
    display_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_primary", "display_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["product"],
                condition=Q(is_primary=True),
                name="one_primary_image_per_product",
            )
        ]

    def __str__(self):
        return f"Image for {self.product.name}"

    def clean(self):
        if self.variant_id and self.variant.product_id != self.product_id:  # type: ignore
            raise ValidationError({"variant": "Variant belongs to a different product."})

    def save(self, *args, **kwargs):
        with transaction.atomic():
            # First image becomes primary; choosing a new primary demotes the old one.
            if not self.product.images.exclude(pk=self.pk).exists():
                self.is_primary = True
            elif self.is_primary:
                self.product.images.exclude(pk=self.pk).update(is_primary=False)
            super().save(*args, **kwargs)