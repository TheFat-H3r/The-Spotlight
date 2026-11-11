from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import Avg, Count, Max, Q
from django.utils import timezone

from orders.models import Order, OrderItem
from products.models import Product

ZERO = Decimal("0.00")
RATING_VALIDATORS = [MinValueValidator(1), MaxValueValidator(5)]


def _to_decimal(value):
    """Averages come back as float or Decimal depending on the DB."""
    if value is None:
        return ZERO
    return Decimal(str(value)).quantize(Decimal("0.01"))


def reviewable_order_items(user):
    """Order lines this user has received and not yet reviewed."""
    return OrderItem.objects.filter(
        order__customer=user,
        order__status=Order.Status.COMPLETED,
        review__isnull=True,
    ).select_related("order__store", "variant__product")


# ---------------------------------------------------------------------------
# Review (one per completed order line or completed booking)
# ---------------------------------------------------------------------------
class ReviewQuerySet(models.QuerySet):
    def public(self):
        """Reviews customers are allowed to see."""
        return self.filter(status=Review.Status.PUBLISHED)


class Review(models.Model):
    class Status(models.TextChoices):
        PUBLISHED = "published", "Published"
        HIDDEN = "hidden", "Hidden by admin"

    # --- Proof of purchase: exactly one of these is set --------------------
    order_item = models.OneToOneField(
        "orders.OrderItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="review",
    )
    booking = models.OneToOneField(
        "bookings.Booking",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="review",
    )

    # --- What is being reviewed (filled automatically from the source) ------
    store = models.ForeignKey(
        "marketplace.Store",
        on_delete=models.CASCADE,
        related_name="reviews",
        editable=False,
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviews",
        editable=False,
    )
    service = models.ForeignKey(
        "bookings.Service",
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
        related_name="reviews",
    )
    author_name = models.CharField(max_length=150, blank=True, editable=False)

    # --- Content -------------------------------------------------------------
    overall_rating = models.PositiveSmallIntegerField(validators=RATING_VALIDATORS)
    title = models.CharField(max_length=120, blank=True)
    body = models.TextField(blank=True)

    # --- Vendor reply -------------------------------------------------------
    reply_text = models.TextField(blank=True)
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

    objects = ReviewQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # On Django < 5.1 use `check=` instead of `condition=`.
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
        return bool(self.order_item_id or self.booking_id)  # type: ignore

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
        """
        Validate the purchase / booking and return (store, product, service).

        ASSUMPTION for the bookings app (not written yet): Booking has
        `customer`, `service` and `status` ("completed"), and Service has
        `store`. Adjust this method if your names differ.
        """
        if bool(self.order_item_id) == bool(self.booking_id):  # type: ignore
            raise ValidationError(
                "A review must be linked to exactly one order item or booking."
            )

        if self.order_item_id:  # type: ignore
            item = self.order_item
            order = item.order  # type: ignore
            if order.status != Order.Status.COMPLETED:
                raise ValidationError("You can review an item once the order is completed.")
            if self.author_id and order.customer_id != self.author_id:  # type: ignore
                raise ValidationError("You can only review items you ordered.")
            product = item.variant.product if item.variant_id else None  # type: ignore
            return order.store, product, None

        booking = self.booking
        if booking.status != "completed":  # type: ignore
            raise ValidationError("You can review a service once the booking is completed.")
        if self.author_id and booking.customer_id != self.author_id:  # type: ignore
            raise ValidationError("You can only review bookings you made.")
        service = booking.service  # type: ignore
        return service.store, None, service

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
        """
        Recompute the denormalised numbers shown around the site:
        Store.rating_*, Product.rating_* and the vendor's VendorReputation.
        Bulk operations (queryset.update/delete) skip this; call it yourself
        or run `VendorReputation.refresh(vendor)` afterwards.
        """
        public = Review.objects.public() # type: ignore

        store_stats = public.filter(store_id=self.store_id).aggregate(  # type: ignore
            avg=Avg("overall_rating"), n=Count("id")
        )
        type(self.store).objects.filter(pk=self.store_id).update(  # type: ignore
            rating_average=_to_decimal(store_stats["avg"]), rating_count=store_stats["n"]
        )

        if self.product_id:  # type: ignore
            product_stats = public.filter(product_id=self.product_id).aggregate(  # type: ignore
                avg=Avg("overall_rating"), n=Count("id")
            )
            Product.objects.filter(pk=self.product_id).update(  # type: ignore
                rating_average=_to_decimal(product_stats["avg"]),
                rating_count=product_stats["n"],
            )

        VendorReputation.refresh(self.store.vendor)

    # -- vendor reply ---------------------------------------------------------
    def add_reply(self, text, by):
        """Let the store's vendor answer this review (editing replaces it)."""
        if by is None or by.pk != self.store.vendor.user_id:
            raise ValidationError("Only the store's vendor can reply to this review.")
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


# ---------------------------------------------------------------------------
# Rating (optional per-aspect scores that sit under a Review)
# ---------------------------------------------------------------------------
class Rating(models.Model):
    class Aspect(models.TextChoices):
        QUALITY = "quality", "Quality"
        VALUE = "value", "Value for money"
        COMMUNICATION = "communication", "Communication"
        PUNCTUALITY = "punctuality", "Punctuality / timeliness"
        ACCURACY = "accuracy", "As described"

    review = models.ForeignKey(
        Review, on_delete=models.CASCADE, related_name="aspect_ratings"
    )
    aspect = models.CharField(max_length=15, choices=Aspect.choices)
    score = models.PositiveSmallIntegerField(validators=RATING_VALIDATORS)

    class Meta:
        ordering = ["review", "aspect"]
        constraints = [
            models.UniqueConstraint(
                fields=["review", "aspect"], name="one_score_per_aspect_per_review"
            ),
            models.CheckConstraint(
                condition=Q(score__range=(1, 5)), name="rating_score_1_to_5"
            ),
        ]

    def __str__(self):
        return f"{self.get_aspect_display()}: {self.score}/5"  # type: ignore

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            VendorReputation.refresh(self.review.store.vendor)

    def delete(self, *args, **kwargs):
        vendor = self.review.store.vendor
        with transaction.atomic():
            result = super().delete(*args, **kwargs)
            VendorReputation.refresh(vendor)
        return result


# ---------------------------------------------------------------------------
# VendorReputation (aggregate across all of a vendor's stores)
# ---------------------------------------------------------------------------
class VendorReputation(models.Model):
    vendor = models.OneToOneField(
        "accounts.VendorProfile", on_delete=models.CASCADE, related_name="reputation"
    )

    rating_average = models.DecimalField(max_digits=3, decimal_places=2, default=ZERO)
    rating_count = models.PositiveIntegerField(default=0)
    distribution = models.JSONField(
        default=dict, blank=True, help_text='Reviews per star, e.g. {"1": 0, ..., "5": 12}.'
    )
    aspect_averages = models.JSONField(
        default=dict, blank=True, help_text='e.g. {"quality": 4.6, "communication": 4.8}.'
    )
    reply_count = models.PositiveIntegerField(default=0)
    last_review_at = models.DateTimeField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-rating_average", "-rating_count"]

    def __str__(self):
        return f"{self.vendor}: {self.rating_average}★ ({self.rating_count})"

    @property
    def positive_percent(self):
        """Share of reviews that are 4 or 5 stars."""
        if not self.rating_count:
            return 0
        good = self.distribution.get("4", 0) + self.distribution.get("5", 0)
        return round(good * 100 / self.rating_count)

    @property
    def response_rate(self):
        """Share of reviews the vendor has replied to."""
        if not self.rating_count:
            return 0
        return round(self.reply_count * 100 / self.rating_count)

    @classmethod
    def refresh(cls, vendor):
        """Recompute everything from published reviews. Safe to call any time."""
        reviews = Review.objects.public().filter(store__vendor=vendor) # type: ignore
        stats = reviews.aggregate(
            avg=Avg("overall_rating"),
            n=Count("id"),
            replies=Count("id", filter=~Q(reply_text="")),
            last=Max("created_at"),
        )

        distribution = {str(i): 0 for i in range(1, 6)}
        for row in reviews.values("overall_rating").annotate(n=Count("id")):
            distribution[str(row["overall_rating"])] = row["n"]

        aspect_rows = (
            Rating.objects.filter(
                review__status=Review.Status.PUBLISHED, review__store__vendor=vendor
            )
            .values("aspect")
            .annotate(avg=Avg("score"))
        )
        aspects = {row["aspect"]: float(_to_decimal(row["avg"])) for row in aspect_rows}

        reputation, _ = cls.objects.update_or_create(
            vendor=vendor,
            defaults={
                "rating_average": _to_decimal(stats["avg"]),
                "rating_count": stats["n"],
                "distribution": distribution,
                "aspect_averages": aspects,
                "reply_count": stats["replies"],
                "last_review_at": stats["last"],
            },
        )
        return reputation