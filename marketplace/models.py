from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify


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


# ---------------------------------------------------------------------------
# BusinessType (the kind of business a store is: Food, Hair & Beauty,
# Transport...). It decides HOW customers deal with the store: by placing
# orders, by making bookings, or both, and which booking flow is used.
# Admins can add new types without any code change.
# ---------------------------------------------------------------------------
class BusinessType(models.Model):
    class Mode(models.TextChoices):
        ORDERS = "orders", "Orders (customers buy products)"
        BOOKINGS = "bookings", "Bookings (customers reserve a time)"
        BOTH = "both", "Orders & bookings"

    class BookingStyle(models.TextChoices):
        APPOINTMENT = "appointment", "Appointment (hair, nails, beauty, tutoring...)"
        TRANSPORT = "transport", "Transport (pickup and drop-off trip)"

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=110, unique=True, blank=True)
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.ORDERS)
    booking_style = models.CharField(
        max_length=12,
        choices=BookingStyle.choices,
        blank=True,
        help_text="Only for types that take bookings. Leave blank for order-only types.",
    )
    description = models.TextField(blank=True)
    icon = models.CharField(
        max_length=50, blank=True, help_text="Emoji or icon name used by the frontend."
    )
    image = models.ImageField(upload_to="business_types/", blank=True, null=True)

    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name

    @property
    def accepts_orders(self):
        return self.mode in (self.Mode.ORDERS, self.Mode.BOTH)

    @property
    def accepts_bookings(self):
        return self.mode in (self.Mode.BOOKINGS, self.Mode.BOTH)

    @property
    def store_type(self):
        """The matching Store.StoreType value."""
        return {
            self.Mode.ORDERS: "products",
            self.Mode.BOOKINGS: "services",
            self.Mode.BOTH: "both",
        }[self.mode]  # type: ignore

    def clean(self):
        if self.accepts_bookings and not self.booking_style:
            raise ValidationError(
                {"booking_style": "Choose a booking style for types that take bookings."}
            )
        if not self.accepts_bookings and self.booking_style:
            raise ValidationError(
                {"booking_style": "Order-only types cannot have a booking style."}
            )

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(BusinessType, self.name, self, max_length=110)
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Category (two levels: e.g. Food > Snacks, Services > Tutoring)
# ---------------------------------------------------------------------------
class Category(models.Model):
    class Kind(models.TextChoices):
        PRODUCT = "product", "Products"
        SERVICE = "service", "Services"
        BOTH = "both", "Products & services"

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=110, unique=True, blank=True)
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
    )
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.BOTH)
    description = models.TextField(blank=True)
    icon = models.CharField(
        max_length=50, blank=True, help_text="Emoji or icon name used by the frontend."
    )
    image = models.ImageField(upload_to="categories/", blank=True, null=True)

    display_order = models.PositiveIntegerField(default=0)
    is_featured = models.BooleanField(
        default=False, help_text="Show on the home page category strip."
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.full_path

    @property
    def is_top_level(self):
        return self.parent_id is None # type: ignore

    @property
    def full_path(self):
        parent = self.parent
        return f"{parent.name} › {self.name}" if parent is not None else self.name

    def clean(self):
        parent = self.parent
        if parent is None:
            return
        if self.pk and parent.pk == self.pk:
            raise ValidationError({"parent": "A category cannot be its own parent."})
        if parent.parent_id is not None:
            raise ValidationError(
                {"parent": "Only two levels are supported. Pick a top-level parent."}
            )

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Category, self.name, self, max_length=110)
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Store (public storefront run by a verified vendor)
# ---------------------------------------------------------------------------
class StoreQuerySet(models.QuerySet):
    def public(self):
        """Stores that customers are allowed to see."""
        return self.filter(
            status=Store.Status.ACTIVE,
            vendor__status="active",
            vendor__user__is_active=True,
        )

    def taking_orders(self):
        """Stores whose business type lets customers place orders."""
        return self.filter(store_type__in=[Store.StoreType.PRODUCTS, Store.StoreType.BOTH])

    def taking_bookings(self):
        """Stores whose business type lets customers make bookings."""
        return self.filter(store_type__in=[Store.StoreType.SERVICES, Store.StoreType.BOTH])


class Store(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft (not public)"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended by admin"

    class StoreType(models.TextChoices):
        PRODUCTS = "products", "Products"
        SERVICES = "services", "Services"
        BOTH = "both", "Products & services"

    vendor = models.ForeignKey(
        "accounts.VendorProfile",
        on_delete=models.CASCADE,
        related_name="stores",
    )

    # Identity
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, unique=True, blank=True)
    tagline = models.CharField(max_length=160, blank=True)
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to="stores/logos/", blank=True, null=True)
    banner = models.ImageField(upload_to="stores/banners/", blank=True, null=True)

    # What the store sells
    # `business_type` is what the vendor picks (Food, Hair & Beauty, Transport...).
    # `store_type` is derived from it on save, so queries stay simple and
    # existing stores keep working until they are given a business type.
    business_type = models.ForeignKey(
        BusinessType,
        on_delete=models.PROTECT,
        null=True,
        related_name="stores",
        help_text="Decides whether the store takes orders, bookings or both.",
    )
    store_type = models.CharField(
        max_length=10,
        choices=StoreType.choices,
        default=StoreType.PRODUCTS,
        editable=False,
        help_text="Derived from the business type.",
    )
    categories = models.ManyToManyField(Category, related_name="stores", blank=True)

    # Contact and fulfilment
    contact_phone = models.CharField(max_length=16, blank=True)
    whatsapp = models.CharField(max_length=16, blank=True)
    pickup_location = models.CharField(
        max_length=150, blank=True, help_text="Where customers collect orders on campus."
    )
    offers_delivery = models.BooleanField(default=False)
    opening_hours = models.JSONField(
        default=dict,
        blank=True,
        help_text='e.g. {"mon": "09:00-17:00", "tue": "09:00-17:00", "sun": null}',
    )
    is_accepting_orders = models.BooleanField(
        default=True, help_text="Vendor can switch this off for breaks or holidays."
    )

    # Visibility and moderation
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    is_featured = models.BooleanField(default=False)

    # Denormalised reputation (updated by the reviews app)
    rating_average = models.DecimalField(max_digits=3, decimal_places=2, default=0) # type: ignore
    rating_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = StoreQuerySet.as_manager()

    class Meta:
        ordering = ["-is_featured", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["vendor", "name"], name="unique_store_name_per_vendor"
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
            and self.vendor.status == "active"
            and self.vendor.user.is_active
        )

    @property
    def accepts_orders(self):
        """True for stores that sell products (cart and checkout)."""
        return self.store_type in (self.StoreType.PRODUCTS, self.StoreType.BOTH)

    @property
    def accepts_bookings(self):
        """True for stores that offer bookable services."""
        return self.store_type in (self.StoreType.SERVICES, self.StoreType.BOTH)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Store, self.name, self, max_length=160)
        if self.business_type_id:  # type: ignore
            self.store_type = self.business_type.store_type  # type: ignore
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# BannerSlot (a named placement on a page; banners are attached to slots
# by the advertising app)
# ---------------------------------------------------------------------------
class BannerSlot(models.Model):
    class Page(models.TextChoices):
        HOME = "home", "Home page"
        CATEGORY = "category", "Category pages"
        STORE = "store", "Store pages"
        SEARCH = "search", "Search results"

    code = models.SlugField(
        max_length=50,
        unique=True,
        help_text="Stable key the frontend asks for, e.g. home-hero.",
    )
    name = models.CharField(max_length=100)
    page = models.CharField(max_length=10, choices=Page.choices, db_index=True)
    description = models.TextField(blank=True)

    # Guidance for designers / validation for uploads
    width = models.PositiveIntegerField(help_text="Recommended width in pixels.")
    height = models.PositiveIntegerField(help_text="Recommended height in pixels.")

    # Behaviour
    max_banners = models.PositiveSmallIntegerField(
        default=1, help_text="How many banners can be live in this slot at once."
    )
    rotation_seconds = models.PositiveSmallIntegerField(
        default=5, help_text="Seconds between banners when several are live. 0 = no rotation."
    )
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["page", "display_order", "name"]

    def __str__(self):
        return f"{self.name} ({self.code})"

    @property
    def recommended_size(self):
        return f"{self.width}×{self.height}px"