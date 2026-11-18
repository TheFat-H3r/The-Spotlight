from django.conf import settings
from django.db import models
from django.template.defaultfilters import slugify

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
  slug = models.SlugField(max_length=110, unique=True)

  class Meta:
    verbose_name_plural = "Categories"

  def __str__(self):
    return self.name


class Store(models.Model):
  class Status(models.TextChoices):
    DRAFT = "draft", "Draft (not public)"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended by admin"

  class StoreType(models.TextChoices):
    PRODUCTS = "products", "Products"
    SERVICES = "services", "Services"
    BOTH = "both", "Products & services"

  # Relationship supporting multi-store ownership via a vendor profile
  owner = models.ForeignKey(
      settings.AUTH_USER_MODEL,
      on_delete=models.CASCADE,
      related_name='stores', blank=False
  )

  # Business Identity
  name = models.CharField(max_length=150, blank=False)
  slug = models.SlugField(max_length=160, unique=True, blank=True)
  tagline = models.CharField(max_length=160, blank=True)
  description = models.TextField(blank=True)
  logo = models.ImageField(upload_to="stores/logos/", blank=True, null=True)
  banner = models.ImageField(upload_to="stores/banners/", blank=True, null=True)

  # Classification & Catalog
  business_type = models.ForeignKey(
      BusinessType,
      on_delete=models.PROTECT,
      null=True,
      blank=False,
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
  contact_phone = models.CharField(max_length=16, blank=True)
  whatsapp = models.CharField(max_length=16, blank=True)
  pickup_location = models.CharField(
      max_length=150, blank=True, help_text="Where customers collect orders."
  )
  offers_delivery = models.BooleanField(default=False)
  opening_hours = models.JSONField(
      default=dict,
      blank=True,
      help_text='e.g. {"mon": "09:00-17:00", "tue": "09:00-17:00", "sun": null}',
  )
  is_accepting_orders = models.BooleanField(
      default=True, help_text="Owner can switch this off for breaks or holidays."
  )

  # Visibility and Moderation
  status = models.CharField(
      max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True
  )
  is_featured = models.BooleanField(default=False)

  # Denormalised reputation (updated by reviews app)
  rating_average = models.DecimalField(max_digits=3, decimal_places=2, default=0)
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
        and getattr(self.owner, "status", None) == "active"
        and getattr(self.owner.user, "is_active", True)
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
    # Auto-generate unique slug if missing
    if not self.slug:
      self.slug = unique_slug(Store, self.name, self, max_length=160)
    if self.business_type_id:  # type: ignore
      self.store_type = self.business_type.store_type  # type: ignore
          
    super().save(*args, **kwargs)
    

    # Derive store_type from selected business_type
    if self.business_type_id: # type: ignore
      self.store_type = self.business_type.store_type


class Service(models.Model):
  store = models.ForeignKey(
      Store, on_delete=models.CASCADE, related_name='services'
  )
  name = models.CharField(max_length=255)
  description = models.TextField(blank=True)
  price = models.DecimalField(max_digits=10, decimal_places=2)

  def __str__(self):
    return f'{self.name} - {self.store.name}'


class Product(models.Model):
  store = models.ForeignKey(
      Store, on_delete=models.CASCADE, related_name='products'
  )
  name = models.CharField(max_length=255)
  description = models.TextField(blank=True)
  price = models.DecimalField(max_digits=10, decimal_places=2)
  stock = models.PositiveIntegerField(default=0)

  def __str__(self):
    return f'{self.name} ({self.store.name})'