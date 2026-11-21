import secrets
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from stores.models import Product, Service

ZERO = Decimal("0.00")
HOLDING_STATUSES = ("pending", "confirmed")


def generate_order_number():
    """Short, human-friendly reference, e.g. SP-261110-A3F9C2."""
    return f"SP-{timezone.now():%y%m%d}-{secrets.token_hex(3).upper()}"


def generate_booking_reference():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no look-alike characters
    return "BK-" + "".join(secrets.choice(alphabet) for _ in range(8))


# ---------------------------------------------------------------------------
# AvailabilitySlot
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
        """Future, active slots on available services that still have free seats."""
        return (
            self.filter(
                is_active=True,
                start_at__gt=timezone.now(),
                service__is_available=True,
            )
            .with_spots()
            .filter(taken_seats__lt=F("total_seats"))
        )


class AvailabilitySlotManager(models.Manager.from_queryset(AvailabilitySlotQuerySet)):
    pass


class AvailabilitySlot(models.Model):
    if TYPE_CHECKING:
        service_id: int
        bookings: models.Manager["Booking"]

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
        default=True,
        help_text="Switch off to block this slot without deleting it.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects: AvailabilitySlotManager = AvailabilitySlotManager()

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
    def total_capacity(self) -> int:
        return self.capacity or getattr(self.service, "capacity", 1)

    @property
    def spots_taken(self) -> int:
        total = self.bookings.filter(status__in=HOLDING_STATUSES).aggregate( # type: ignore
            total=Sum("seats")
        )["total"]
        return total or 0

    @property
    def spots_left(self) -> int:
        return max(self.total_capacity - self.spots_taken, 0)

    @property
    def is_bookable(self) -> bool:
        return (
            self.is_active
            and self.start_at > timezone.now()
            and self.spots_left > 0
            and self.service.is_available
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
            .select_related("service__store__owner")
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
class Booking(models.Model):
    if TYPE_CHECKING:
        customer_id: int
        service_id: int
        slot_id: int

        def get_status_display(self) -> str: ...

    class Status(models.TextChoices):
        PENDING = "pending", "Pending vendor approval"
        CONFIRMED = "confirmed", "Confirmed"
        REJECTED = "rejected", "Rejected by vendor"
        CANCELLED_BY_CUSTOMER = "cancelled_by_customer", "Cancelled by customer"
        CANCELLED_BY_VENDOR = "cancelled_by_vendor", "Cancelled by vendor"
        COMPLETED = "completed", "Completed"
        NO_SHOW = "no_show", "Customer did not show up"

    HOLDING_STATUSES = HOLDING_STATUSES

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
        max_digits=10, decimal_places=2, default=ZERO, editable=False
    )

    customer_note = models.TextField(blank=True, default="")
    customer_phone = models.CharField(max_length=16, blank=True, default="")
    # Only used by transport services
    pickup_location = models.CharField(max_length=150, blank=True, default="")
    dropoff_location = models.CharField(max_length=150, blank=True, default="")
    vendor_note = models.TextField(blank=True, default="")
    status_reason = models.TextField(
        blank=True, default="", help_text="Why it was rejected or cancelled."
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
        return f"{self.reference} – {self.service.name} ({self.get_status_display()})"

    # -- convenience ---------------------------------------------------------
    @property
    def store(self):
        return self.service.store

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
            window_hours = getattr(self.service, "cancellation_window_hours", 0)
            deadline = self.slot.start_at - timedelta(hours=window_hours)
            return timezone.now() < deadline
        return False

    # -- validation ----------------------------------------------------------
    def clean(self):
        if not (self.slot_id and self.service_id):
            return
        slot, service = self.slot, self.service
        errors = {}

        if slot.service_id != service.pk:
            errors["slot"] = "This slot does not belong to the selected service."

        if self._state.adding and not errors:
            now = timezone.now()
            min_notice = getattr(service, "min_notice_hours", 0)
            max_advance = getattr(service, "max_advance_days", 90)

            if not service.is_available:
                errors["service"] = "This service is not available for booking."
            elif not slot.is_active:
                errors["slot"] = "This slot is not available."
            elif slot.start_at < now + timedelta(hours=min_notice):
                errors["slot"] = f"Bookings need at least {min_notice}h notice."
            elif slot.start_at > now + timedelta(days=max_advance):
                errors["slot"] = f"Bookings can only be made {max_advance} days ahead."
            elif self.seats > slot.spots_left:
                errors["seats"] = f"Only {slot.spots_left} seat(s) left in this slot."

            if service.store.owner_id == self.customer_id:
                errors["customer"] = "You cannot book your own service."

            if getattr(service, "is_transport", False):
                if not self.pickup_location:
                    errors["pickup_location"] = "Pickup location is required for transport."
                if not self.dropoff_location:
                    errors["dropoff_location"] = "Drop-off location is required for transport."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self._state.adding:
            if self.slot_id and not self.service_id:
                self.service_id = self.slot.service_id
            if hasattr(self.service, "price_for"):
                self.total_price = self.service.price_for(self.seats)
            else:
                self.total_price = self.service.starting_price * self.seats

            if self.status == self.Status.PENDING and not getattr(
                self.service, "requires_approval", True
            ):
                self.status = self.Status.CONFIRMED
                self.confirmed_at = timezone.now()
        super().save(*args, **kwargs)

    # -- status transitions --------------------------------------------------
    def _move_to(self, new_status, allowed_from, **fields):
        if self.status not in allowed_from:
            raise ValidationError(
                f"A {self.get_status_display().lower()} booking cannot become "
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
    edit_request_url = None


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------
class OrderQuerySet(models.QuerySet):
    def for_customer(self, user):
        return self.filter(customer=user)

    def for_vendor(self, user):
        return self.filter(store__owner=user)

    def open(self):
        """Orders that are still in progress."""
        return self.exclude(status__in=Order.TERMINAL_STATUSES)


class OrderManager(models.Manager.from_queryset(OrderQuerySet)):
    pass


class Order(models.Model):
    if TYPE_CHECKING:
        customer_id: int | None
        store_id: int
        items: models.Manager["OrderItem"]

        def get_status_display(self) -> str: ...

    class Status(models.TextChoices):
        PENDING = "pending", "Pending (awaiting vendor)"
        CONFIRMED = "confirmed", "Confirmed"
        PREPARING = "preparing", "Preparing"
        READY = "ready", "Ready for pickup / delivery"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        REJECTED = "rejected", "Rejected by vendor"

    class Fulfilment(models.TextChoices):
        PICKUP = "pickup", "Campus pickup"
        DELIVERY = "delivery", "Delivery"

    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Cash on pickup / delivery"
        MOBILE_MONEY = "mobile_money", "Mobile money"
        CARD = "card", "Card / gateway"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PAID = "paid", "Paid"
        REFUNDED = "refunded", "Refunded"

    # Which statuses can follow which. Views and serializers should rely on this.
    TRANSITIONS = {
        Status.PENDING: [Status.CONFIRMED, Status.REJECTED, Status.CANCELLED],
        Status.CONFIRMED: [Status.PREPARING, Status.READY, Status.CANCELLED],
        Status.PREPARING: [Status.READY, Status.CANCELLED],
        Status.READY: [Status.COMPLETED, Status.CANCELLED],
        Status.COMPLETED: [],
        Status.CANCELLED: [],
        Status.REJECTED: [],
    }
    TERMINAL_STATUSES = [Status.COMPLETED, Status.CANCELLED, Status.REJECTED]
    RELEASES_STOCK = [Status.CANCELLED, Status.REJECTED]
    CUSTOMER_CANCELLABLE = [Status.PENDING]

    order_number = models.CharField(
        max_length=20, unique=True, editable=False, default=generate_order_number
    )
    checkout_reference = models.UUIDField(
        db_index=True,
        default=uuid.uuid4,
        help_text="Shared by all orders created in the same checkout.",
    )

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    store = models.ForeignKey(
        "stores.Store", on_delete=models.PROTECT, related_name="orders"
    )

    # Snapshot of contact details at the time of ordering
    customer_name = models.CharField(max_length=150, blank=True, default="")
    customer_phone = models.CharField(max_length=16, blank=True, default="")
    customer_email = models.EmailField(blank=True, default="")

    # Fulfilment
    fulfilment_method = models.CharField(
        max_length=10, choices=Fulfilment.choices, default=Fulfilment.PICKUP
    )
    pickup_location = models.CharField(max_length=150, blank=True, default="")
    delivery_address = models.CharField(max_length=255, blank=True, default="")

    # Lifecycle
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    customer_note = models.TextField(blank=True, default="")
    vendor_note = models.TextField(blank=True, default="")
    cancel_reason = models.CharField(max_length=255, blank=True, default="")

    # Payment (placeholder until the payments approach is decided)
    payment_method = models.CharField(
        max_length=15, choices=PaymentMethod.choices, default=PaymentMethod.CASH
    )
    payment_status = models.CharField(
        max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID
    )
    payment_reference = models.CharField(max_length=100, blank=True, default="")

    # Money (frozen at checkout)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    discount_total = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    coupon_code = models.CharField(
        max_length=40, blank=True, default=""
    )  # used by advertising app
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    objects: OrderManager = OrderManager()

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(total__gte=0), name="order_total_non_negative"
            )
        ]
        indexes = [
            models.Index(fields=["customer", "-created_at"]),
            models.Index(fields=["store", "status"]),
        ]

    def __str__(self):
        return f"{self.order_number} · {self.store}"

    # -- helpers ------------------------------------------------------------
    @property
    def is_open(self):
        return self.status not in self.TERMINAL_STATUSES

    @property
    def can_customer_cancel(self):
        return self.status in self.CUSTOMER_CANCELLABLE

    @property
    def item_count(self):
        return sum(i.quantity for i in self.items.all()) # type: ignore

    def allowed_next_statuses(self):
        return list(self.TRANSITIONS.get(self.status, []))

    def recalculate_totals(self):
        self.subtotal = sum((i.line_total for i in self.items.all()), ZERO) # type: ignore
        self.total = max(self.subtotal - self.discount_total + self.delivery_fee, ZERO)

    def save(self, *args, **kwargs):
        if not self.order_number:
            number = generate_order_number()
            while Order.objects.filter(order_number=number).exists():
                number = generate_order_number()
            self.order_number = number
        super().save(*args, **kwargs)

    # -- lifecycle ----------------------------------------------------------
    def change_status(self, new_status, by=None, note=""):
        """
        Move the order to `new_status`, validating the transition, adjusting
        stock, stamping timestamps and writing an OrderStatusHistory row.
        """
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=self.pk)
            if new_status not in order.allowed_next_statuses():
                raise ValidationError(
                    f"Cannot change an order from “{order.get_status_display()}” "
                    f"to “{dict(self.Status.choices).get(new_status, new_status)}”."
                )

            old_status = order.status
            now = timezone.now()
            items = order.items.select_related("product")

            if new_status in self.RELEASES_STOCK:
                for item in items:
                    if item.product_id:
                        Product.objects.filter(pk=item.product_id).update(
                            stock=F("stock") + item.quantity
                        )
                order.cancelled_at = now
                if note:
                    order.cancel_reason = note[:255]
            elif new_status == self.Status.CONFIRMED:
                order.confirmed_at = now
            elif new_status == self.Status.COMPLETED:
                for item in items:
                    if item.product_id:
                        Product.objects.filter(pk=item.product_id).update(
                            stock=F("stock") - item.quantity
                        )
                order.completed_at = now
                if order.payment_method == self.PaymentMethod.CASH:
                    order.payment_status = self.PaymentStatus.PAID

            order.status = new_status
            order.save()
            OrderStatusHistory.objects.create(
                order=order,
                from_status=old_status,
                to_status=new_status,
                changed_by=by,
                note=note,
            )

        # keep the caller's instance in sync
        for field in (
            "status",
            "confirmed_at",
            "completed_at",
            "cancelled_at",
            "cancel_reason",
            "payment_status",
            "updated_at",
        ):
            setattr(self, field, getattr(order, field))
        return self


# ---------------------------------------------------------------------------
# OrderItem (price and names are snapshots, so later edits never change history)
# ---------------------------------------------------------------------------
class OrderItem(models.Model):
    if TYPE_CHECKING:
        order_id: int
        product_id: int | None

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_items",
    )
    product_name = models.CharField(max_length=150)
    variant_name = models.CharField(max_length=100, blank=True, default="")
    sku = models.CharField(max_length=50, blank=True, default="")
    unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(ZERO)]
    )
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.quantity} × {self.display_name}"

    @property
    def display_name(self):
        if self.variant_name:
            return f"{self.product_name} — {self.variant_name}"
        return self.product_name

    @property
    def line_total(self):
        return self.unit_price * self.quantity


# ---------------------------------------------------------------------------
# OrderStatusHistory (audit trail shown as the tracking timeline)
# ---------------------------------------------------------------------------
class OrderStatusHistory(models.Model):
    if TYPE_CHECKING:
        changed_by_id: int | None
        order_id: int

    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="status_history"
    )
    from_status = models.CharField(
        max_length=10, choices=Order.Status.choices, blank=True, default=""
    )
    to_status = models.CharField(max_length=10, choices=Order.Status.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name_plural = "order status history"

    def __str__(self):
        return f"{self.order.order_number}: {self.from_status or '—'} → {self.to_status}"

class Cart(models.Model):
    if TYPE_CHECKING:
        customer_id: int
        items: models.Manager["CartItem"]

    customer = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cart",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def total_items(self) -> int:
        return sum(item.quantity for item in self.items.all()) # type: ignore

    @property
    def subtotal(self) -> Decimal:
        return sum((item.line_total for item in self.items.all()), ZERO) # type: ignore

    def __str__(self):
        return f"Cart #{self.pk} - {self.customer.email}"


class CartItem(models.Model):
    if TYPE_CHECKING:
        cart_id: int
        product_id: int

    cart = models.ForeignKey(
        Cart, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="cart_items"
    )
    variant_name = models.CharField(max_length=100, blank=True, default="")
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    selected_options = models.JSONField(default=dict, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["added_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["cart", "product"],
                name="unique_product_per_cart"
            )
        ]

    @property
    def line_total(self) -> Decimal: 
        return self.product.price * self.quantity

    def __str__(self):
        return f"{self.quantity} × {self.product.name}"


class VendorNotification(models.Model):
    store = models.ForeignKey(
        "stores.Store", on_delete=models.CASCADE, related_name="notifications"
    )
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="notifications", null=True, blank=True
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.store} — {self.title}"