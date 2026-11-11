import secrets
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import F, Q
from django.utils import timezone

from products.models import Product

ZERO = Decimal("0.00")


def generate_order_number():
    """Short, human-friendly reference, e.g. SP-261110-A3F9C2."""
    return f"SP-{timezone.now():%y%m%d}-{secrets.token_hex(3).upper()}"


def variant_is_purchasable(variant):
    """Single place that decides whether a variant can go in a cart / order."""
    product = variant.product
    return (
        variant.is_active
        and product.is_public
        and product.store.is_accepting_orders
    )


# ---------------------------------------------------------------------------
# Cart (one per customer; may hold items from several stores)
# ---------------------------------------------------------------------------
class Cart(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cart"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart of {self.user}"

    # -- read helpers -------------------------------------------------------
    @property
    def total_items(self):
        return sum(item.quantity for item in self.items.all())  # type: ignore

    @property
    def subtotal(self):
        return sum((item.line_total for item in self.items.all()), ZERO)  # type: ignore

    # -- changes ------------------------------------------------------------
    def add(self, variant, quantity=1):
        """Add units of a variant, merging with an existing line."""
        if quantity < 1:
            raise ValidationError("Quantity must be at least 1.")
        if not variant_is_purchasable(variant):
            raise ValidationError(f"“{variant}” is not available right now.")
        if variant.product.store.vendor.user_id == self.user_id:  # type: ignore
            raise ValidationError("You cannot buy from your own store.")

        with transaction.atomic():
            item, _ = CartItem.objects.select_for_update().get_or_create(
                cart=self, variant=variant, defaults={"quantity": 0}
            )
            new_qty = item.quantity + quantity
            if not variant.inventory.can_fulfil(new_qty):
                raise ValidationError(f"Only {variant.inventory.available} left in stock.")
            item.quantity = new_qty
            item.save(update_fields=["quantity", "updated_at"])
        return item

    def set_quantity(self, variant, quantity):
        """Set an exact quantity. 0 removes the line."""
        if quantity <= 0:
            return self.remove(variant)
        if not variant.inventory.can_fulfil(quantity):
            raise ValidationError(f"Only {variant.inventory.available} left in stock.")
        item = self.items.get(variant=variant)  # type: ignore
        item.quantity = quantity
        item.save(update_fields=["quantity", "updated_at"])
        return item

    def remove(self, variant):
        self.items.filter(variant=variant).delete()  # type: ignore

    def clear(self):
        self.items.all().delete()  # type: ignore

    # -- checkout -----------------------------------------------------------
    def checkout(
        self,
        *,
        contact_phone,
        fulfilment_method="pickup",
        delivery_address="",
        payment_method="cash",
        customer_note="",
    ):
        """
        Turn the cart into one Order per store (each vendor fulfils their own),
        reserve stock, and empty the cart. All-or-nothing: if anything fails
        (e.g. an item sold out) nothing is created and nothing is reserved.
        Returns the list of created orders.
        """
        with transaction.atomic():
            items = list(
                self.items.select_related(  # type: ignore
                    "variant__product__store__vendor__user",
                    "variant__product__category",
                    "variant__inventory",
                ).order_by("variant_id")  # consistent lock order avoids deadlocks
            )
            if not items:
                raise ValidationError("Your cart is empty.")

            by_store = {}
            for item in items:
                variant = item.variant
                store = variant.product.store
                if not variant_is_purchasable(variant):
                    raise ValidationError(f"“{variant}” is no longer available.")
                if store.vendor.user_id == self.user_id:  # type: ignore
                    raise ValidationError("You cannot buy from your own store.")
                by_store.setdefault(store.pk, (store, []))[1].append(item)

            if fulfilment_method == Order.Fulfilment.DELIVERY:
                if not delivery_address.strip():
                    raise ValidationError("A delivery address is required.")
                for store, _ in by_store.values():
                    if not store.offers_delivery:
                        raise ValidationError(f"{store.name} does not offer delivery.")

            checkout_reference = uuid.uuid4()
            orders = []
            for store, store_items in by_store.values():
                order = Order(
                    checkout_reference=checkout_reference,
                    customer=self.user,
                    store=store,
                    customer_name=self.user.get_full_name() or str(self.user),
                    customer_phone=contact_phone,
                    customer_email=getattr(self.user, "email", ""),
                    fulfilment_method=fulfilment_method,
                    pickup_location=store.pickup_location,
                    delivery_address=delivery_address
                    if fulfilment_method == Order.Fulfilment.DELIVERY
                    else "",
                    payment_method=payment_method,
                    customer_note=customer_note,
                )
                order.subtotal = sum(
                    (i.line_total for i in store_items), ZERO
                )
                order.total = order.subtotal
                order.save()

                order_items = []
                for i in store_items:
                    i.variant.inventory.reserve(i.quantity)  # raises if sold out
                    order_items.append(
                        OrderItem(
                            order=order,
                            variant=i.variant,
                            product_name=i.variant.product.name,
                            variant_name=""
                            if i.variant.is_default
                            else i.variant.name,
                            sku=i.variant.sku,
                            unit_price=i.unit_price,
                            quantity=i.quantity,
                        )
                    )
                OrderItem.objects.bulk_create(order_items)

                OrderStatusHistory.objects.create(
                    order=order,
                    from_status="",
                    to_status=order.status,
                    changed_by=self.user,
                    note="Order placed.",
                )
                orders.append(order)

            self.clear()
        return orders


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey(
        "products.Variant", on_delete=models.CASCADE, related_name="cart_items"
    )
    quantity = models.PositiveIntegerField(
        default=1, validators=[MinValueValidator(1)]
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["cart", "variant"], name="unique_variant_per_cart"
            )
        ]

    def __str__(self):
        return f"{self.quantity} × {self.variant}"

    @property
    def unit_price(self):
        """Always the live price; it is frozen into OrderItem at checkout."""
        return self.variant.effective_price

    @property
    def line_total(self):
        return self.unit_price * self.quantity

    @property
    def is_available(self):
        return variant_is_purchasable(self.variant) and self.variant.inventory.can_fulfil(
            self.quantity
        )


# ---------------------------------------------------------------------------
# Order (one per store per checkout; the vendor's unit of work)
# ---------------------------------------------------------------------------
class OrderQuerySet(models.QuerySet):
    def for_customer(self, user):
        return self.filter(customer=user)

    def for_vendor(self, vendor_profile):
        return self.filter(store__vendor=vendor_profile)

    def open(self):
        """Orders that are still in progress."""
        return self.exclude(status__in=Order.TERMINAL_STATUSES)


class Order(models.Model):
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

    order_number = models.CharField(max_length=20, unique=True, editable=False)
    checkout_reference = models.UUIDField(
        db_index=True,
        help_text="Shared by all orders created in the same checkout.",
    )

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="orders",
    )
    store = models.ForeignKey(
        "marketplace.Store", on_delete=models.PROTECT, related_name="orders"
    )

    # Snapshot of contact details at the time of ordering
    customer_name = models.CharField(max_length=150)
    customer_phone = models.CharField(max_length=16)
    customer_email = models.EmailField(blank=True)

    # Fulfilment
    fulfilment_method = models.CharField(
        max_length=10, choices=Fulfilment.choices, default=Fulfilment.PICKUP
    )
    pickup_location = models.CharField(max_length=150, blank=True)
    delivery_address = models.CharField(max_length=255, blank=True)

    # Lifecycle
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    customer_note = models.TextField(blank=True)
    vendor_note = models.TextField(blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)

    # Payment (placeholder until the payments approach is decided)
    payment_method = models.CharField(
        max_length=15, choices=PaymentMethod.choices, default=PaymentMethod.CASH
    )
    payment_status = models.CharField(
        max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID
    )
    payment_reference = models.CharField(max_length=100, blank=True)

    # Money (frozen at checkout)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    discount_total = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    coupon_code = models.CharField(max_length=40, blank=True)  # used by advertising app
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    objects = OrderQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # On Django < 5.1 use `check=` instead of `condition=`.
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
        return sum(i.quantity for i in self.items.all())  # type: ignore

    def allowed_next_statuses(self):
        return list(self.TRANSITIONS.get(self.status, []))

    def recalculate_totals(self):
        self.subtotal = sum((i.line_total for i in self.items.all()), ZERO)  # type: ignore
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
        Who may trigger which change is the view's job (e.g. customers may
        only cancel while `can_customer_cancel`).
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
            items = order.items.select_related("variant__inventory")  # type: ignore

            if new_status in self.RELEASES_STOCK:
                for item in items:
                    if item.variant_id:
                        item.variant.inventory.release(item.quantity)
                order.cancelled_at = now
                if note:
                    order.cancel_reason = note[:255]
            elif new_status == self.Status.CONFIRMED:
                order.confirmed_at = now
            elif new_status == self.Status.COMPLETED:
                for item in items:
                    if item.variant_id:
                        item.variant.inventory.deduct(item.quantity)
                        Product.objects.filter(
                            pk=item.variant.product_id
                        ).update(sold_count=F("sold_count") + item.quantity)
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
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey(
        "products.Variant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_items",
    )

    product_name = models.CharField(max_length=150)
    variant_name = models.CharField(max_length=100, blank=True)
    sku = models.CharField(max_length=50, blank=True)
    unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(ZERO)]
    )
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])

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

    @property
    def product(self):
        """The live product, or None if it has since been deleted."""
        return self.variant.product if self.variant_id else None  # type: ignore


# ---------------------------------------------------------------------------
# OrderStatusHistory (audit trail shown as the tracking timeline)
# ---------------------------------------------------------------------------
class OrderStatusHistory(models.Model):
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="status_history"
    )
    from_status = models.CharField(max_length=10, choices=Order.Status.choices, blank=True)
    to_status = models.CharField(max_length=10, choices=Order.Status.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name_plural = "order status history"

    def __str__(self):
        return f"{self.order.order_number}: {self.from_status or '—'} → {self.to_status}"