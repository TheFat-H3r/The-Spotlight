from decimal import Decimal
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import Avg, Count, Q
from django.template.defaultfilters import slugify
from django.utils import timezone

ZERO = Decimal("0.00")
RATING_VALIDATORS = [MinValueValidator(1), MaxValueValidator(5)]


def unique_slug(model_class, value, instance=None, max_length=150):
    """Build a slug from `value` that is unique within `model_class`."""
    base = slugify(value)[: max_length - 6] or model_class._meta.model_name
    queryset = model_class.objects.all()
    if instance is not None and instance.pk:
        queryset = queryset.exclude(pk=instance.pk)

    slug, n = base, 2
    while queryset.filter(slug=slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


class BusinessType(models.Model):
    """Defines categories of businesses (e.g., Food, Hair & Beauty, Delivery)."""

    class StoreType(models.TextChoices):
        PRODUCTS = "products", "Products"
        SERVICES = "services", "Services"
        BOTH = "both", "Products & services"

    name = models.CharField(max_length=100, unique=True)
    store_type = models.CharField(
        max_length=10,
        choices=StoreType.choices,
        default=StoreType.PRODUCTS,
        help_text="Determines if stores under this type handle products, services, or both.",
    )

    def __str__(self):
        return self.name


class Category(models.Model):
    """Public browsing categories for stores."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=110, unique=True, blank=True)

    class Meta:
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Category, self.name, self, max_length=110)
        super().save(*args, **kwargs)


class Store(models.Model):
    if TYPE_CHECKING:
        business_type_id: int | None
        owner_id: int

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft (not public)"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended by admin"

    class StoreType(models.TextChoices):
        PRODUCTS = "products", "Products"
        SERVICES = "services", "Services"
        BOTH = "both", "Products & services"

    # Relationship supporting multi-store ownership
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="stores",
    )

    # Business Identity
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, unique=True, blank=True)
    tagline = models.CharField(max_length=160, blank=True, default="")
    description = models.TextField(blank=True, default="")
    logo = models.ImageField(upload_to="stores/logos/", blank=True, null=True)
    banner = models.ImageField(upload_to="stores/banners/", blank=True, null=True)

    # Classification & Catalog
    business_type = models.ForeignKey(
        BusinessType,
        on_delete=models.PROTECT,
        related_name="stores",
        help_text="Decides whether the store takes orders, bookings or both.",
    )
    store_type = models.CharField(
        max_length=10,
        choices=StoreType.choices,
        default=StoreType.PRODUCTS,
        editable=False,
        help_text="Derived automatically from the business type.",
    )
    categories = models.ManyToManyField(Category, related_name="stores", blank=True)

    # Contact and Fulfillment
    contact_phone = models.CharField(max_length=16, blank=True, default="")
    contact_email = models.EmailField(blank=True, default="")
    whatsapp = models.CharField(max_length=16, blank=True, default="")
    social_links = models.JSONField(default=dict, blank=True)
    pickup_location = models.CharField(
        max_length=150,
        blank=True,
        default="",
        help_text="Where customers collect orders.",
    )
    offers_delivery = models.BooleanField(default=False)
    opening_hours = models.JSONField(
        default=dict,
        blank=True,
        help_text='e.g. {"mon": "09:00-17:00", "tue": "09:00-17:00", "sun": null}',
    )
    is_accepting_orders = models.BooleanField(
        default=True,
        help_text="Owner can switch this off for breaks or holidays.",
    )

    # Visibility and Moderation
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    is_featured = models.BooleanField(default=False)

    # Denormalised reputation (updated by reviews app)
    rating_average = models.DecimalField(max_digits=3, decimal_places=2, default=ZERO)
    rating_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_featured", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "name"], name="unique_store_name_per_owner"
            )
        ]
        indexes = [
            models.Index(fields=["status", "is_featured"]),
            models.Index(fields=["business_type", "status"]),
        ]

    def __str__(self):
        return self.name

    @property
    def is_public(self):
        return (
            self.status == self.Status.ACTIVE
            and getattr(self.owner, "status", "active") == "active"
            and getattr(self.owner, "is_active", True)
        )

    @property
    def accepts_orders(self):
        """True for stores that sell products via cart and checkout."""
        return self.store_type in (self.StoreType.PRODUCTS, self.StoreType.BOTH)

    @property
    def accepts_bookings(self):
        """True for stores that offer bookable services."""
        return self.store_type in (self.StoreType.SERVICES, self.StoreType.BOTH)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Store, self.name, self, max_length=160)
        if self.business_type_id:
            self.store_type = self.business_type.store_type
        super().save(*args, **kwargs)


class Service(models.Model):
    if TYPE_CHECKING:
        category_id: int | None
        store_id: int

    store = models.ForeignKey(
        Store, on_delete=models.CASCADE, related_name="services"
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=265, unique=True, blank=False, help_text="Auto-generated from the name if left blank.")
    description = models.TextField(blank=True, default="")
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="services",
    )
    starting_price = models.DecimalField(
        max_digits=10, decimal_places=2, default=ZERO, blank=True
    )
    image = models.ImageField(upload_to="services/images/", blank=True, null=True)
    is_available = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - {self.store.name}"


class Product(models.Model):
    if TYPE_CHECKING:
        category_id: int | None
        store_id: int

    store = models.ForeignKey(
        Store, on_delete=models.CASCADE, related_name="products"
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, blank=False, help_text="Auto-generated from the name if left blank.")
    description = models.TextField(blank=True, default="")
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    price = models.DecimalField(
        max_digits=10, decimal_places=2, default=ZERO, blank=True
    )
    image = models.ImageField(upload_to="products/images/", blank=True, null=True)
    stock = models.PositiveIntegerField(default=0)
    is_available = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)

    # Denormalised reputation (updated by Review.refresh_aggregates)
    rating_average = models.DecimalField(max_digits=3, decimal_places=2, default=ZERO)
    rating_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.store.name})"


def _to_decimal(value):
    """Averages come back as float or Decimal depending on the DB."""
    if value is None:
        return ZERO
    return Decimal(str(value)).quantize(Decimal("0.01"))


class ReviewQuerySet(models.QuerySet):
    def public(self):
        """Reviews customers are allowed to see."""
        return self.filter(status=Review.Status.PUBLISHED)


class ReviewManager(models.Manager.from_queryset(ReviewQuerySet)):
    pass


class Review(models.Model):
    if TYPE_CHECKING:
        author_id: int | None
        booking_id: int | None
        order_item_id: int | None
        product_id: int | None
        replied_by_id: int | None
        service_id: int | None
        store_id: int

    class Status(models.TextChoices):
        PUBLISHED = "published", "Published"
        HIDDEN = "hidden", "Hidden by admin"

    # --- Proof of purchase: exactly one of these is set --------------------
    order_item = models.OneToOneField(
        "transactions.OrderItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="review",
    )
    booking = models.OneToOneField(
        "transactions.Booking",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="review",
    )

    # --- What is being reviewed (filled automatically from the source) ------
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="reviews",
        editable=False,
    )
    product = models.ForeignKey(
        "stores.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviews",
        editable=False,
    )
    service = models.ForeignKey(
        "stores.Service",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviews",
        editable=False,
    )

    # --- Author (kept as a snapshot so reviews survive account deletion) ----
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviews",
    )
    author_name = models.CharField(
        max_length=150, blank=True, default="", editable=False
    )

    # --- Content -------------------------------------------------------------
    overall_rating = models.PositiveSmallIntegerField(validators=RATING_VALIDATORS)
    title = models.CharField(max_length=120, blank=True, default="")
    body = models.TextField(blank=True, default="")

    # --- Vendor reply -------------------------------------------------------
    reply_text = models.TextField(blank=True, default="")
    replied_at = models.DateTimeField(null=True, blank=True)
    replied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    # --- Moderation ---------------------------------------------------------
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PUBLISHED, db_index=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects: ReviewManager = ReviewManager()

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(overall_rating__range=(1, 5)),
                name="review_overall_rating_1_to_5",
            ),
            models.CheckConstraint(
                condition=(
                    Q(order_item__isnull=False, booking__isnull=True)
                    | Q(order_item__isnull=True, booking__isnull=False)
                ),
                name="review_has_exactly_one_source",
            ),
        ]
        indexes = [
            models.Index(fields=["store", "status", "-created_at"]),
            models.Index(fields=["product", "status"]),
            models.Index(fields=["author"]),
        ]

    def __str__(self):
        return f"{self.overall_rating}★ for {self.store} by {self.display_author}"

    # -- helpers ------------------------------------------------------------
    @property
    def is_verified(self):
        """Always true by construction: every review has a purchase or booking."""
        return bool(self.order_item_id or self.booking_id)

    @property
    def has_reply(self):
        return bool(self.reply_text)

    @property
    def display_author(self):
        """Public name such as 'Jane D.' (full names are never shown)."""
        parts = (self.author_name or "").split()
        if not parts:
            return "Student"
        if len(parts) == 1:
            return parts[0]
        return f"{parts[0]} {parts[-1][0]}."

    # -- verification -------------------------------------------------------
    def _resolve_source(self):
        """Validate the purchase / booking and return (store, product, service)."""
        if bool(self.order_item_id) == bool(self.booking_id):
            raise ValidationError(
                "A review must be linked to exactly one order item or booking."
            )

        if self.order_item is not None:
            item = self.order_item
            order = item.order
            if order.status != "completed":
                raise ValidationError(
                    "You can review an item once the order is completed."
                )
            if self.author_id and order.customer_id != self.author_id:
                raise ValidationError("You can only review items you ordered.")
            product = item.variant.product if getattr(item, "variant_id", None) else None
            return order.store, product, None

        if self.booking is not None:
            booking = self.booking
            if booking.status != "completed":
                raise ValidationError(
                    "You can review a service once the booking is completed."
                )
            if self.author_id and booking.customer_id != self.author_id:
                raise ValidationError("You can only review bookings you made.")
            service = booking.service
            return service.store, None, service

        raise ValidationError(
            "A review must be linked to exactly one order item or booking."
        )

    def clean(self):
        if self._state.adding:
            self._resolve_source()

    # -- saving & aggregates --------------------------------------------------
    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self._state.adding:
                self.store, self.product, self.service = self._resolve_source()
                if self.author and not self.author_name:
                    self.author_name = self.author.get_full_name() or str(self.author)
            super().save(*args, **kwargs)
            self.refresh_aggregates()

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            result = super().delete(*args, **kwargs)
            self.refresh_aggregates()
        return result

    def refresh_aggregates(self):
        """Recompute denormalised rating averages and counts."""
        public = Review.objects.public() # type: ignore

        store_stats = public.filter(store_id=self.store_id).aggregate(
            avg=Avg("overall_rating"), n=Count("id")
        )
        Store.objects.filter(pk=self.store_id).update(
            rating_average=_to_decimal(store_stats["avg"]),
            rating_count=store_stats["n"],
        )

        if self.product_id:
            product_stats = public.filter(product_id=self.product_id).aggregate(
                avg=Avg("overall_rating"), n=Count("id")
            )
            Product.objects.filter(pk=self.product_id).update(
                rating_average=_to_decimal(product_stats["avg"]),
                rating_count=product_stats["n"],
            )

    # -- vendor reply ---------------------------------------------------------
    def add_reply(self, text, by):
        """Let the store's owner answer this review (editing replaces it)."""
        if by is None or by.pk != self.store.owner_id:
            raise ValidationError("Only the store's owner can reply to this review.")
        text = (text or "").strip()
        if not text:
            raise ValidationError("A reply cannot be empty.")
        self.reply_text = text
        self.replied_by = by
        self.replied_at = timezone.now()
        self.save(update_fields=["reply_text", "replied_by", "replied_at", "updated_at"])
        return self

    def remove_reply(self):
        self.reply_text = ""
        self.replied_by = None
        self.replied_at = None
        self.save(update_fields=["reply_text", "replied_by", "replied_at", "updated_at"])