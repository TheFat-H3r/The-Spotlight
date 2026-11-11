from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import F, Q
from django.utils import timezone

from orders.models import Order

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def exactly_one(*fields):
    """Q for a CheckConstraint: exactly one of `fields` is not NULL."""
    result = Q()
    for field in fields:
        condition = Q(**{f"{field}__isnull": False})
        for other in fields:
            if other != field:
                condition &= Q(**{f"{other}__isnull": True})
        result |= condition
    return result


def public_store_q(prefix):
    """
    Q for 'this store is visible to customers', mirroring Store.is_public.
    `prefix` is the path to the store, e.g. "store__" or "product__store__".
    """
    return Q(
        **{
            f"{prefix}status": "active",
            f"{prefix}vendor__status": "active",
            f"{prefix}vendor__user__is_active": True,
        }
    )


class PromoStatus(models.TextChoices):
    PENDING = "pending", "Pending approval"
    ACTIVE = "active", "Approved / active"
    PAUSED = "paused", "Paused"
    REJECTED = "rejected", "Rejected"


# ---------------------------------------------------------------------------
# Shared abstract bases
# ---------------------------------------------------------------------------
class PromoQuerySet(models.QuerySet):
    def in_window(self, at=None):
        """Started and not yet ended (ends_at empty = open-ended)."""
        at = at or timezone.now()
        return self.filter(starts_at__lte=at).filter(
            Q(ends_at__isnull=True) | Q(ends_at__gt=at)
        )

    def record_impressions(self):
        """Count one view for every row in the queryset (single UPDATE)."""
        return self.update(impressions=F("impressions") + 1)

    def record_clicks(self):
        return self.update(clicks=F("clicks") + 1)


class PromoBase(models.Model):
    """Schedule + performance counters shared by every kind of promotion."""

    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(
        null=True, blank=True, help_text="Leave empty to run until paused."
    )

    impressions = models.PositiveIntegerField(default=0, editable=False)
    clicks = models.PositiveIntegerField(default=0, editable=False)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    @property
    def is_scheduled_now(self):
        now = timezone.now()
        return self.starts_at <= now and (self.ends_at is None or self.ends_at > now)

    @property
    def ctr(self):
        """Click-through rate as a percentage."""
        if not self.impressions:
            return 0
        return round(self.clicks * 100 / self.impressions, 2)

    def record_impression(self):
        type(self).objects.filter(pk=self.pk).update(impressions=F("impressions") + 1)

    def record_click(self):
        type(self).objects.filter(pk=self.pk).update(clicks=F("clicks") + 1)

    def _schedule_errors(self):
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            return {"ends_at": "The end must be after the start."}
        return {}


class ReviewedPromo(PromoBase):
    """Paid / vendor-created promotions that an admin approves first."""

    status = models.CharField(
        max_length=10,
        choices=PromoStatus.choices,
        default=PromoStatus.PENDING,
        db_index=True,
    )
    fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=ZERO,
        validators=[MinValueValidator(ZERO)],
        help_text="Amount the vendor paid for this promotion (0 = free / platform).",
    )
    payment_reference = models.CharField(max_length=100, blank=True)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=255, blank=True)

    class Meta(PromoBase.Meta):
        abstract = True

    @property
    def state(self):
        """What the dashboard shows: pending, rejected, paused, scheduled, live, ended."""
        if self.status == PromoStatus.PENDING:
            return "pending"
        if self.status == PromoStatus.REJECTED:
            return "rejected"
        if self.status == PromoStatus.PAUSED:
            return "paused"
        now = timezone.now()
        if self.starts_at > now:
            return "scheduled"
        if self.ends_at is not None and self.ends_at <= now:
            return "ended"
        return "live"

    # -- workflow -----------------------------------------------------------
    def _activate(self):
        previous = self.status
        self.status = PromoStatus.ACTIVE
        try:
            self.clean()  # e.g. a banner slot may be full
        except ValidationError:
            self.status = previous
            raise

    def approve(self, by):
        self._activate()
        self.reviewed_by = by
        self.reviewed_at = timezone.now()
        self.rejection_reason = ""
        self.save(
            update_fields=[
                "status",
                "reviewed_by",
                "reviewed_at",
                "rejection_reason",
                "updated_at",
            ]
        )

    def reject(self, by, reason=""):
        self.status = PromoStatus.REJECTED
        self.reviewed_by = by
        self.reviewed_at = timezone.now()
        self.rejection_reason = reason[:255]
        self.save(
            update_fields=[
                "status",
                "reviewed_by",
                "reviewed_at",
                "rejection_reason",
                "updated_at",
            ]
        )

    def pause(self):
        if self.status != PromoStatus.ACTIVE:
            raise ValidationError("Only an active promotion can be paused.")
        self.status = PromoStatus.PAUSED
        self.save(update_fields=["status", "updated_at"])

    def resume(self):
        if self.status != PromoStatus.PAUSED:
            raise ValidationError("Only a paused promotion can be resumed.")
        self._activate()
        self.save(update_fields=["status", "updated_at"])


# ---------------------------------------------------------------------------
# SponsoredListing (a vendor pays to boost a product, service or whole store)
# ---------------------------------------------------------------------------
class SponsoredListingQuerySet(PromoQuerySet):
    def live(self, at=None):
        return self.filter(status=PromoStatus.ACTIVE).in_window(at)

    def visible(self, at=None):
        """
        Live listings whose store is public and whose product (if any) is active.
        NOTE: add a matching condition for `service` once bookings.Service
        has its own status / is_active field.
        """
        return (
            self.live(at)
            .filter(public_store_q("store__"))
            .filter(Q(product__isnull=True) | Q(product__status="active"))
        )


class SponsoredListing(ReviewedPromo):
    class Placement(models.TextChoices):
        HOME = "home", "Home page"
        CATEGORY = "category", "Category page"
        SEARCH = "search", "Search results"

    store = models.ForeignKey(
        "marketplace.Store",
        on_delete=models.CASCADE,
        related_name="sponsored_listings",
    )
    # Leave both empty to promote the store itself.
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sponsored_listings",
    )
    service = models.ForeignKey(
        "bookings.Service",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sponsored_listings",
    )

    placement = models.CharField(
        max_length=10, choices=Placement.choices, default=Placement.SEARCH
    )
    category = models.ForeignKey(
        "marketplace.Category",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sponsored_listings",
        help_text="Required for category-page placement.",
    )
    keywords = models.JSONField(
        default=list,
        blank=True,
        help_text='Search terms that trigger this listing, e.g. ["braids", "hair"].',
    )
    weight = models.PositiveSmallIntegerField(
        default=1, help_text="Higher weight is shown first among sponsored results."
    )

    objects = SponsoredListingQuerySet.as_manager()

    class Meta(ReviewedPromo.Meta):
        ordering = ["-weight", "-starts_at"]
        constraints = [
            # On Django < 5.1 use `check=` instead of `condition=`.
            models.CheckConstraint(
                condition=Q(ends_at__isnull=True) | Q(ends_at__gt=F("starts_at")),
                name="sponsoredlisting_ends_after_start",
            ),
            models.CheckConstraint(
                condition=~Q(product__isnull=False, service__isnull=False),
                name="sponsoredlisting_product_or_service",
            ),
            models.CheckConstraint(
                condition=~Q(placement="category") | Q(category__isnull=False),
                name="sponsoredlisting_category_placement_needs_category",
            ),
        ]
        indexes = [
            models.Index(fields=["placement", "status", "starts_at", "ends_at"]),
            models.Index(fields=["store", "status"]),
        ]

    def __str__(self):
        return f"Sponsored: {self.target} ({self.get_placement_display()})"  # type: ignore

    @property
    def target(self):
        return self.product or self.service or self.store

    @property
    def target_type(self):
        if self.product_id:  # type: ignore
            return "product"
        if self.service_id:  # type: ignore
            return "service"
        return "store"

    def clean(self):
        errors = self._schedule_errors()
        if self.product_id and self.service_id:  # type: ignore
            errors["service"] = "Promote either a product or a service, not both."
        if self.store_id:  # type: ignore
            if self.product_id and self.product.store_id != self.store_id:  # type: ignore
                errors["product"] = "This product belongs to a different store."
            if self.service_id and self.service.store_id != self.store_id:  # type: ignore
                errors["service"] = "This service belongs to a different store."
        if self.placement == self.Placement.CATEGORY and not self.category_id:  # type: ignore
            errors["category"] = "Pick a category for category-page placement."
        if errors:
            raise ValidationError(errors)


# ---------------------------------------------------------------------------
# PromoBanner (an image placed in a marketplace.BannerSlot)
# ---------------------------------------------------------------------------
class PromoBannerQuerySet(PromoQuerySet):
    def live(self, at=None):
        return self.filter(status=PromoStatus.ACTIVE, slot__is_active=True).in_window(at)

    def visible(self, at=None):
        """Live banners; vendor banners only while their store is public."""
        return self.live(at).filter(Q(store__isnull=True) | public_store_q("store__"))

    def for_slot(self, code):
        return self.visible().filter(slot__code=code)


class PromoBanner(ReviewedPromo):
    slot = models.ForeignKey(
        "marketplace.BannerSlot", on_delete=models.PROTECT, related_name="banners"
    )
    store = models.ForeignKey(
        "marketplace.Store",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="promo_banners",
        help_text="Empty for a platform banner.",
    )

    title = models.CharField(max_length=120)
    subtitle = models.CharField(max_length=200, blank=True)
    cta_label = models.CharField(
        max_length=30, blank=True, help_text='Button text, e.g. "Shop now".'
    )
    link_url = models.CharField(
        max_length=255,
        blank=True,
        help_text="Frontend route (/stores/my-shop) or a full URL.",
    )

    image = models.ImageField(
        upload_to="promos/banners/", width_field="image_width", height_field="image_height"
    )
    image_width = models.PositiveIntegerField(null=True, blank=True, editable=False)
    image_height = models.PositiveIntegerField(null=True, blank=True, editable=False)
    mobile_image = models.ImageField(upload_to="promos/banners/mobile/", blank=True, null=True)
    alt_text = models.CharField(max_length=150, blank=True)

    display_order = models.PositiveIntegerField(default=0)

    objects = PromoBannerQuerySet.as_manager()

    class Meta(ReviewedPromo.Meta):
        ordering = ["slot", "display_order", "-starts_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__isnull=True) | Q(ends_at__gt=F("starts_at")),
                name="promobanner_ends_after_start",
            )
        ]
        indexes = [
            models.Index(fields=["slot", "status", "starts_at", "ends_at"]),
            models.Index(fields=["store", "status"]),
        ]

    def __str__(self):
        return f"{self.title} → {self.slot.code}"  # type: ignore

    def _slot_errors(self):
        """Respect BannerSlot.max_banners and the slot's recommended proportions."""
        errors = {}
        slot = self.slot

        # Aspect ratio within 5% of the slot's recommended size.
        if self.image_width and self.image_height and slot.height:
            expected = slot.width / slot.height
            actual = self.image_width / self.image_height
            if abs(actual - expected) / expected > 0.05:
                errors["image"] = (
                    f"This slot uses a {slot.recommended_size} banner "
                    f"(you uploaded {self.image_width}×{self.image_height}px)."
                )

        # Don't exceed the number of banners that may be live at once.
        if self.status == PromoStatus.ACTIVE:
            overlapping = PromoBanner.objects.filter(
                slot=slot, status=PromoStatus.ACTIVE
            ).exclude(pk=self.pk)
            overlapping = overlapping.filter(
                Q(ends_at__isnull=True) | Q(ends_at__gt=self.starts_at)
            )
            if self.ends_at is not None:
                overlapping = overlapping.filter(starts_at__lt=self.ends_at)
            if overlapping.count() >= slot.max_banners:
                errors["slot"] = (
                    f"“{slot.name}” already has {slot.max_banners} banner(s) "
                    "booked for these dates."
                )
        return errors

    def clean(self):
        errors = self._schedule_errors()
        if self.slot_id:  # type: ignore
            errors.update(self._slot_errors())
        if errors:
            raise ValidationError(errors)


# ---------------------------------------------------------------------------
# FeaturedItem (admin-curated entries that power the "featured feed")
# ---------------------------------------------------------------------------
class FeaturedItemQuerySet(PromoQuerySet):
    def live(self, at=None):
        return self.filter(is_active=True).in_window(at)

    def visible(self, at=None):
        """Live entries whose target is itself visible to customers."""
        product_ok = Q(product__isnull=False, product__status="active") & public_store_q(
            "product__store__"
        )
        store_ok = Q(store__isnull=False) & public_store_q("store__")
        service_ok = Q(service__isnull=False) & public_store_q("service__store__")
        venture_ok = Q(venture__isnull=False)  # add a published check in portfolios
        return self.live(at).filter(product_ok | store_ok | service_ok | venture_ok)

    def for_section(self, section):
        return self.visible().filter(section=section)


class FeaturedItem(PromoBase):
    class Section(models.TextChoices):
        HOME_PRODUCTS = "home_products", "Home: featured products"
        HOME_SERVICES = "home_services", "Home: featured services"
        TOP_VENDORS = "top_vendors", "Home: top vendors"
        VENTURES = "ventures", "Home: featured student ventures"

    # Which kind of target each section accepts.
    SECTION_TARGET = {
        Section.HOME_PRODUCTS: "product",
        Section.HOME_SERVICES: "service",
        Section.TOP_VENDORS: "store",
        Section.VENTURES: "venture",
    }

    section = models.CharField(max_length=15, choices=Section.choices, db_index=True)

    # Exactly one target, matching the section.
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="featured_entries",
    )
    service = models.ForeignKey(
        "bookings.Service",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="featured_entries",
    )
    store = models.ForeignKey(
        "marketplace.Store",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="featured_entries",
    )
    venture = models.ForeignKey(
        "accounts.VendorProfile",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="featured_entries",
    )

    # Optional editorial overrides
    custom_title = models.CharField(max_length=120, blank=True)
    custom_blurb = models.CharField(max_length=200, blank=True)
    image = models.ImageField(upload_to="promos/featured/", blank=True, null=True)

    position = models.PositiveIntegerField(
        default=0, help_text="Lower numbers appear first within the section."
    )
    is_active = models.BooleanField(default=True)

    objects = FeaturedItemQuerySet.as_manager()

    class Meta(PromoBase.Meta):
        ordering = ["section", "position", "-starts_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__isnull=True) | Q(ends_at__gt=F("starts_at")),
                name="featureditem_ends_after_start",
            ),
            models.CheckConstraint(
                condition=exactly_one("product", "service", "store", "venture"),
                name="featureditem_exactly_one_target",
            ),
        ]
        indexes = [models.Index(fields=["section", "is_active", "position"])]

    def __str__(self):
        return f"{self.get_section_display()}: {self.target}"  # type: ignore

    @property
    def target(self):
        return self.product or self.service or self.store or self.venture

    @property
    def title(self):
        return self.custom_title or str(self.target)

    def clean(self):
        errors = self._schedule_errors()
        wanted = self.SECTION_TARGET.get(self.section)  # type: ignore
        filled = [
            name
            for name in ("product", "service", "store", "venture")
            if getattr(self, f"{name}_id")
        ]
        if len(filled) != 1:
            errors["__all__"] = "Choose exactly one target to feature."
        elif wanted and filled[0] != wanted:
            errors[filled[0]] = f"This section features a {wanted}, not a {filled[0]}."
        if errors:
            raise ValidationError(errors)


# ---------------------------------------------------------------------------
# Coupon (platform-wide or store-specific discount codes)
# ---------------------------------------------------------------------------
class Coupon(models.Model):
    class DiscountType(models.TextChoices):
        PERCENT = "percent", "Percentage off"
        FIXED = "fixed", "Fixed amount off"

    code = models.CharField(
        max_length=40, unique=True, help_text="Stored in capitals, e.g. WELCOME10."
    )
    description = models.CharField(max_length=200, blank=True)

    store = models.ForeignKey(
        "marketplace.Store",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="coupons",
        help_text="Leave empty for a platform-wide coupon.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    # Discount
    discount_type = models.CharField(
        max_length=10, choices=DiscountType.choices, default=DiscountType.PERCENT
    )
    value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(CENT)],
        help_text="Percent (1–100) or an amount, depending on the type.",
    )
    max_discount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Cap for percentage coupons.",
    )
    min_order_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=ZERO, validators=[MinValueValidator(ZERO)]
    )

    # Limits
    usage_limit = models.PositiveIntegerField(
        null=True, blank=True, help_text="Total redemptions allowed. Empty = unlimited."
    )
    per_user_limit = models.PositiveIntegerField(
        null=True, blank=True, default=1, help_text="Per customer. Empty = unlimited."
    )
    first_order_only = models.BooleanField(
        default=False, help_text="Only for customers with no earlier order."
    )
    times_used = models.PositiveIntegerField(default=0, editable=False)

    # Validity
    valid_from = models.DateTimeField(default=timezone.now)
    valid_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(value__gt=0), name="coupon_value_positive"
            ),
            models.CheckConstraint(
                condition=~Q(discount_type="percent") | Q(value__lte=100),
                name="coupon_percent_max_100",
            ),
            models.CheckConstraint(
                condition=Q(valid_until__isnull=True) | Q(valid_until__gt=F("valid_from")),
                name="coupon_ends_after_start",
            ),
        ]
        indexes = [models.Index(fields=["store", "is_active"])]

    def __str__(self):
        return self.code

    # -- helpers ------------------------------------------------------------
    @property
    def is_live(self):
        now = timezone.now()
        return (
            self.is_active
            and self.valid_from <= now
            and (self.valid_until is None or self.valid_until > now)
        )

    @property
    def is_exhausted(self):
        return self.usage_limit is not None and self.times_used >= self.usage_limit

    @property
    def label(self):
        """Short text for the UI, e.g. '10% off' or '5.00 off'."""
        if self.discount_type == self.DiscountType.PERCENT:
            return f"{self.value.normalize():f}% off"
        return f"{self.value} off"

    def clean(self):
        errors = {}
        if self.discount_type == self.DiscountType.PERCENT and self.value and self.value > 100:
            errors["value"] = "A percentage cannot be more than 100."
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            errors["valid_until"] = "Must be after the start date."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper()
        super().save(*args, **kwargs)

    # -- applying -----------------------------------------------------------
    def discount_for(self, subtotal):
        """Discount in money for `subtotal`. Never more than the subtotal."""
        subtotal = Decimal(subtotal)
        if self.discount_type == self.DiscountType.PERCENT:
            discount = (subtotal * self.value / 100).quantize(CENT, ROUND_HALF_UP)
            if self.max_discount is not None:
                discount = min(discount, self.max_discount)
        else:
            discount = self.value
        return max(min(discount, subtotal), ZERO)

    def validate_for(self, user, store, subtotal, exclude_order=None):
        """
        Check every rule for this customer and store. Returns the discount
        amount, or raises ValidationError with a message fit to show the user.
        """
        now = timezone.now()
        if not self.is_active:
            raise ValidationError("This coupon is not active.")
        if self.valid_from > now:
            raise ValidationError("This coupon is not valid yet.")
        if self.valid_until is not None and self.valid_until <= now:
            raise ValidationError("This coupon has expired.")
        if self.store_id and self.store_id != store.pk:  # type: ignore
            raise ValidationError("This coupon doesn't apply to this store.")
        if self.is_exhausted:
            raise ValidationError("This coupon has been fully redeemed.")
        if user is None:
            raise ValidationError("Sign in to use a coupon.")

        if self.per_user_limit is not None:
            used = CouponRedemption.objects.filter(coupon=self, user=user).count()
            if used >= self.per_user_limit:
                raise ValidationError("You have already used this coupon.")

        if self.first_order_only:
            earlier = Order.objects.filter(customer=user).exclude(
                status__in=[Order.Status.CANCELLED, Order.Status.REJECTED]
            )
            if exclude_order is not None:
                earlier = earlier.exclude(pk=exclude_order.pk)
            if earlier.exists():
                raise ValidationError("This coupon is only for your first order.")

        if Decimal(subtotal) < self.min_order_amount:
            raise ValidationError(
                f"Spend at least {self.min_order_amount} to use this coupon."
            )

        discount = self.discount_for(subtotal)
        if discount <= 0:
            raise ValidationError("This coupon gives no discount on this order.")
        return discount

    def redeem(self, order, user=None):
        """
        Apply the coupon to a new (pending) order: records the redemption,
        counts the use, and updates the order's discount and total.
        """
        user = user or order.customer
        with transaction.atomic():
            coupon = Coupon.objects.select_for_update().get(pk=self.pk)

            if order.status != Order.Status.PENDING:
                raise ValidationError("Coupons can only be applied to new orders.")
            if CouponRedemption.objects.filter(order=order).exists():
                raise ValidationError("This order already has a coupon.")

            discount = coupon.validate_for(
                user, order.store, order.subtotal, exclude_order=order
            )
            CouponRedemption.objects.create(
                coupon=coupon, user=user, order=order, discount_amount=discount
            )
            Coupon.objects.filter(pk=coupon.pk).update(times_used=F("times_used") + 1)

            order.discount_total = discount
            order.coupon_code = coupon.code
            order.recalculate_totals()
            order.save(
                update_fields=[
                    "discount_total",
                    "coupon_code",
                    "subtotal",
                    "total",
                    "updated_at",
                ]
            )
        self.times_used = coupon.times_used + 1
        return discount

    @classmethod
    def release_for_order(cls, order):
        """
        Give the use back when an order is cancelled or rejected, so the
        customer can try the coupon again. The order keeps its recorded discount.
        """
        with transaction.atomic():
            redemption = (
                CouponRedemption.objects.select_for_update().filter(order=order).first()
            )
            if redemption is None:
                return False
            cls.objects.filter(pk=redemption.coupon_id, times_used__gt=0).update(  # type: ignore
                times_used=F("times_used") - 1
            )
            redemption.delete()
        return True


# ---------------------------------------------------------------------------
# CouponRedemption (audit trail; powers the per-customer limit)
# ---------------------------------------------------------------------------
class CouponRedemption(models.Model):
    coupon = models.ForeignKey(
        Coupon, on_delete=models.PROTECT, related_name="redemptions"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="coupon_redemptions",
    )
    order = models.OneToOneField(
        "orders.Order", on_delete=models.PROTECT, related_name="coupon_redemption"
    )
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["coupon", "user"])]

    def __str__(self):
        return f"{self.coupon.code} on {self.order.order_number}"  # type: ignore