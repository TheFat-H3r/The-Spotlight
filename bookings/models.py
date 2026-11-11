import secrets
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from marketplace.models import Category, Store, unique_slug

# Booking statuses that occupy seats in a slot. Rejected, cancelled, completed
# and no-show bookings release (or no longer need) their seats.
HOLDING_STATUSES = ("pending", "confirmed")


# ---------------------------------------------------------------------------
# Service (a bookable offering that belongs to a Store)
# ---------------------------------------------------------------------------
class ServiceQuerySet(models.QuerySet):
    def public(self):
        """Services that customers are allowed to see and book."""
        return self.filter(
            is_active=True,
            store__status=Store.Status.ACTIVE,
            store__vendor__status="active",
            store__vendor__user__is_active=True,
            store__store_type__in=[Store.StoreType.SERVICES, Store.StoreType.BOTH],
        )


class Service(models.Model):
    class PriceUnit(models.TextChoices):
        FIXED = "fixed", "Per session"
        HOURLY = "hourly", "Per hour"
        PER_PERSON = "per_person", "Per person"

    class LocationType(models.TextChoices):
        VENDOR = "vendor", "At the vendor's location"
        CUSTOMER = "customer", "At the customer's location"
        ONLINE = "online", "Online"

    # Type hints only; Django creates these attributes for the foreign keys.
    store_id: int
    category_id: int | None

    store = models.ForeignKey(
        Store, on_delete=models.CASCADE, related_name="services"
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="services",
        limit_choices_to=Q(kind__in=["service", "both"]),
    )

    # Identity
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, unique=True, blank=True)
    short_description = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="services/", blank=True, null=True)

    # Pricing
    price = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    price_unit = models.CharField(
        max_length=12, choices=PriceUnit.choices, default=PriceUnit.FIXED
    )

    # Scheduling rules
    duration_minutes = models.PositiveSmallIntegerField(
        default=60,
        validators=[MinValueValidator(5)],
        help_text="Length of one session.",
    )
    capacity = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text="Default seats per slot (1 = one customer at a time, more for group sessions).",
    )
    min_notice_hours = models.PositiveSmallIntegerField(
        default=2, help_text="Customers must book at least this many hours ahead."
    )
    max_advance_days = models.PositiveSmallIntegerField(
        default=60, help_text="Customers cannot book further ahead than this."
    )
    cancellation_window_hours = models.PositiveSmallIntegerField(
        default=12,
        help_text="Customers can cancel a confirmed booking until this many hours before the start.",
    )
    requires_approval = models.BooleanField(
        default=True,
        help_text="If off, bookings are confirmed automatically without vendor approval.",
    )

    # Where it happens
    location_type = models.CharField(
        max_length=10, choices=LocationType.choices, default=LocationType.VENDOR
    )
    location_details = models.CharField(
        max_length=200,
        blank=True,
        help_text="Meeting point on campus, or the video-call link/instructions.",
    )

    is_active = models.BooleanField(
        default=True, help_text="Vendor can switch a service off without deleting it."
    )

    # Denormalised reputation (updated by the reviews app)
    rating_average = models.DecimalField(max_digits=3, decimal_places=2, default=0)  # type: ignore
    rating_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ServiceQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["store", "name"], name="unique_service_name_per_store"
            )
        ]
        indexes = [models.Index(fields=["is_active", "store"])]

    def __str__(self):
        return f"{self.name} ({self.store.name})"

    @property
    def is_public(self):
        return self.is_active and self.store.is_public and self.store.accepts_bookings

    @property
    def booking_style(self):
        """'appointment' (hair, nails, beauty...) or 'transport', from the store's business type."""
        business_type = self.store.business_type
        if business_type is not None and business_type.booking_style:
            return business_type.booking_style
        return "appointment"

    @property
    def is_transport(self):
        return self.booking_style == "transport"

    def price_for(self, seats=1):
        """Total price for one booking of this service."""
        if self.price_unit == self.PriceUnit.HOURLY:
            return (self.price * self.duration_minutes / Decimal(60)).quantize(
                Decimal("0.01")
            )
        if self.price_unit == self.PriceUnit.PER_PERSON:
            return self.price * seats
        return self.price

    def clean(self):
        errors = {}
        if self.store_id and not self.store.accepts_bookings:  # type: ignore
            errors["store"] = (
                "This store's business type does not take bookings "
                "(it is an orders-only business)."
            )
        if self.category_id and self.category.kind == Category.Kind.PRODUCT:  # type: ignore
            errors["category"] = "Pick a category that is meant for services."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Service, self.name, self, max_length=160)
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# AvailabilitySlot (a concrete bookable time window for a service)
# ---------------------------------------------------------------------------
class AvailabilitySlotQuerySet(models.QuerySet):
    def with_spots(self):
        """Annotate `total_seats`, `taken_seats` for the slot."""
        return self.annotate(
            total_seats=Coalesce("capacity", "service__capacity"),
            taken_seats=Coalesce(
                Sum("bookings__seats", filter=Q(bookings__status__in=HOLDING_STATUSES)),
                0,
            ),
        )

    def available(self):
        """Future, active slots on public services that still have free seats."""
        return (
            self.filter(
                is_active=True,
                start_at__gt=timezone.now(),
                service__in=Service.objects.public(), # type: ignore
            )
            .with_spots()
            .filter(taken_seats__lt=F("total_seats"))
        )


class AvailabilitySlot(models.Model):
    service_id: int  # type hint only; Django creates this attribute for the FK

    service = models.ForeignKey(
        Service, on_delete=models.CASCADE, related_name="slots"
    )
    start_at = models.DateTimeField(db_index=True)
    end_at = models.DateTimeField()
    capacity = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="Leave blank to use the service's default capacity.",
    )
    is_active = models.BooleanField(
        default=True, help_text="Switch off to block this slot without deleting it."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = AvailabilitySlotQuerySet.as_manager()

    class Meta:
        ordering = ["start_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_at__gt=F("start_at")),
                name="slot_ends_after_it_starts",
            ),
            models.UniqueConstraint(
                fields=["service", "start_at"], name="unique_slot_start_per_service"
            ),
        ]
        indexes = [models.Index(fields=["service", "start_at"])]

    def __str__(self):
        return f"{self.service.name}: {self.start_at:%a %d %b %Y, %H:%M}–{self.end_at:%H:%M}"

    @property
    def total_capacity(self):
        return self.capacity or self.service.capacity

    @property
    def spots_taken(self):
        total = self.bookings.filter(status__in=HOLDING_STATUSES).aggregate(  # type: ignore
            total=Sum("seats")
        )["total"]
        return total or 0

    @property
    def spots_left(self):
        return max(self.total_capacity - self.spots_taken, 0)

    @property
    def is_bookable(self):
        return (
            self.is_active
            and self.start_at > timezone.now()
            and self.spots_left > 0
            and self.service.is_public
        )

    def clean(self):
        errors = {}
        if self.start_at and self.end_at:
            if self.end_at <= self.start_at:
                errors["end_at"] = "End time must be after the start time."
            elif self.service_id:
                overlapping = AvailabilitySlot.objects.filter(
                    service_id=self.service_id,
                    start_at__lt=self.end_at,
                    end_at__gt=self.start_at,
                )
                if self.pk:
                    overlapping = overlapping.exclude(pk=self.pk)
                if overlapping.exists():
                    errors["start_at"] = "This overlaps another slot for the same service."
        if errors:
            raise ValidationError(errors)

    @transaction.atomic
    def book(self, customer, seats=1, note="", phone=""):
        """
        Create a booking for this slot.

        The slot row is locked first so two customers cannot grab the last
        seat at the same time. Raises ValidationError if the booking is invalid.
        """
        slot = (
            AvailabilitySlot.objects.select_for_update()
            .select_related("service__store__vendor__user")
            .get(pk=self.pk)
        )
        booking = Booking(
            customer=customer,
            service=slot.service,
            slot=slot,
            seats=seats,
            customer_note=note,
            customer_phone=phone,
        )
        booking.full_clean()
        booking.save()
        return booking


# ---------------------------------------------------------------------------
# Booking (a customer's reservation of a slot)
# ---------------------------------------------------------------------------
def generate_booking_reference():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no look-alike characters
    return "BK-" + "".join(secrets.choice(alphabet) for _ in range(8))


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending vendor approval"
        CONFIRMED = "confirmed", "Confirmed"
        REJECTED = "rejected", "Rejected by vendor"
        CANCELLED_BY_CUSTOMER = "cancelled_by_customer", "Cancelled by customer"
        CANCELLED_BY_VENDOR = "cancelled_by_vendor", "Cancelled by vendor"
        COMPLETED = "completed", "Completed"
        NO_SHOW = "no_show", "Customer did not show up"

    HOLDING_STATUSES = HOLDING_STATUSES

    # Type hints only; Django creates these attributes for the foreign keys.
    customer_id: int
    service_id: int
    slot_id: int

    reference = models.CharField(
        max_length=12, unique=True, editable=False, default=generate_booking_reference
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="bookings",
    )
    service = models.ForeignKey(
        Service, on_delete=models.PROTECT, related_name="bookings"
    )
    slot = models.ForeignKey(
        AvailabilitySlot, on_delete=models.PROTECT, related_name="bookings"
    )
    seats = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1)], help_text="Number of people."
    )

    status = models.CharField(
        max_length=25, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    # Price is frozen when the booking is made, so later edits to the service
    # do not change what the customer agreed to.
    total_price = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, editable=False  # type: ignore
    )

    customer_note = models.TextField(blank=True)
    customer_phone = models.CharField(max_length=16, blank=True)
    # Only used by transport services
    pickup_location = models.CharField(max_length=150, blank=True)
    dropoff_location = models.CharField(max_length=150, blank=True)
    vendor_note = models.TextField(blank=True)
    status_reason = models.TextField(
        blank=True, help_text="Why it was rejected or cancelled."
    )

    confirmed_at = models.DateTimeField(null=True, blank=True)
    responded_at = models.DateTimeField(
        null=True, blank=True, help_text="When the vendor approved or rejected."
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # One live booking per customer per slot (cancelled ones don't count).
            models.UniqueConstraint(
                fields=["customer", "slot"],
                condition=Q(status__in=HOLDING_STATUSES),
                name="one_active_booking_per_customer_slot",
            )
        ]
        indexes = [
            models.Index(fields=["customer", "status"]),
            models.Index(fields=["service", "status"]),
        ]

    def __str__(self):
        return f"{self.reference} – {self.service.name} ({self.get_status_display()})"  # type: ignore

    # -- convenience ---------------------------------------------------------
    @property
    def store(self):
        return self.service.store

    @property
    def vendor(self):
        return self.service.store.vendor

    @property
    def start_at(self):
        return self.slot.start_at

    @property
    def end_at(self):
        return self.slot.end_at

    @property
    def is_holding_seats(self):
        return self.status in HOLDING_STATUSES

    @property
    def can_customer_cancel(self):
        if self.status == self.Status.PENDING:
            return self.slot.start_at > timezone.now()
        if self.status == self.Status.CONFIRMED:
            deadline = self.slot.start_at - timedelta(
                hours=self.service.cancellation_window_hours
            )
            return timezone.now() < deadline
        return False

    # -- validation ----------------------------------------------------------
    def clean(self):
        if not (self.slot_id and self.service_id):
            return
        slot, service = self.slot, self.service
        errors = {}

        if slot.service_id != service.pk:  # type: ignore
            errors["slot"] = "This slot does not belong to the selected service."

        if self._state.adding and not errors:
            now = timezone.now()
            if not service.is_public:
                errors["service"] = "This service is not available for booking."
            elif not slot.is_active:
                errors["slot"] = "This slot is not available."
            elif slot.start_at < now + timedelta(hours=service.min_notice_hours):
                errors["slot"] = (
                    f"Bookings need at least {service.min_notice_hours}h notice."
                )
            elif slot.start_at > now + timedelta(days=service.max_advance_days):
                errors["slot"] = (
                    f"Bookings can only be made {service.max_advance_days} days ahead."
                )
            elif self.seats > slot.spots_left:
                errors["seats"] = f"Only {slot.spots_left} seat(s) left in this slot."

            if service.store.vendor.user_id == self.customer_id:  # type: ignore
                errors["customer"] = "You cannot book your own service."

            if service.is_transport:
                if not self.pickup_location:
                    errors["pickup_location"] = "Pickup location is required for transport."
                if not self.dropoff_location:
                    errors["dropoff_location"] = "Drop-off location is required for transport."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self._state.adding:
            if self.slot_id and not self.service_id:
                self.service_id = self.slot.service_id  # type: ignore
            self.total_price = self.service.price_for(self.seats)
            if (
                self.status == self.Status.PENDING
                and not self.service.requires_approval
            ):
                self.status = self.Status.CONFIRMED
                self.confirmed_at = timezone.now()
        super().save(*args, **kwargs)

    # -- status transitions --------------------------------------------------
    def _move_to(self, new_status, allowed_from, **fields):
        if self.status not in allowed_from:
            raise ValidationError(
                f"A {self.get_status_display().lower()} booking cannot become "  # type: ignore
                f"{self.Status(new_status).label.lower()}."
            )
        self.status = new_status
        for name, value in fields.items():
            setattr(self, name, value)
        self.save(update_fields=["status", "updated_at", *fields.keys()])

    def approve(self, note=""):
        """Vendor accepts a pending booking."""
        now = timezone.now()
        self._move_to(
            self.Status.CONFIRMED,
            [self.Status.PENDING],
            confirmed_at=now,
            responded_at=now,
            vendor_note=note or self.vendor_note,
        )

    def reject(self, reason=""):
        """Vendor declines a pending booking. Its seats are released."""
        now = timezone.now()
        self._move_to(
            self.Status.REJECTED,
            [self.Status.PENDING],
            responded_at=now,
            status_reason=reason,
        )

    def cancel_by_customer(self, reason=""):
        if not self.can_customer_cancel:
            raise ValidationError(
                "This booking can no longer be cancelled. "
                "Please contact the vendor."
            )
        self._move_to(
            self.Status.CANCELLED_BY_CUSTOMER,
            [self.Status.PENDING, self.Status.CONFIRMED],
            cancelled_at=timezone.now(),
            status_reason=reason,
        )

    def cancel_by_vendor(self, reason=""):
        self._move_to(
            self.Status.CANCELLED_BY_VENDOR,
            [self.Status.PENDING, self.Status.CONFIRMED],
            cancelled_at=timezone.now(),
            status_reason=reason,
        )

    def complete(self):
        """Mark a confirmed booking as done. Unlocks reviews for the customer."""
        if self.slot.start_at > timezone.now():
            raise ValidationError("A booking cannot be completed before it starts.")
        self._move_to(
            self.Status.COMPLETED,
            [self.Status.CONFIRMED],
            completed_at=timezone.now(),
        )

    def mark_no_show(self):
        if self.slot.start_at > timezone.now():
            raise ValidationError("A booking cannot be a no-show before it starts.")
        self._move_to(self.Status.NO_SHOW, [self.Status.CONFIRMED])