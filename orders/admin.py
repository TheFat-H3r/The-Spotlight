from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db.models import Sum

from .models import Cart, CartItem, Order, OrderItem, OrderStatusHistory


# ---------------------------------------------------------------------------
# Inlines (read-only: orders are created by checkout, never by hand)
# ---------------------------------------------------------------------------
class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ("display_name", "sku", "unit_price", "quantity", "line_total")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="Item")
    def display_name(self, obj):
        return obj.display_name

    @admin.display(description="Line total")
    def line_total(self, obj):
        return obj.line_total


class OrderStatusHistoryInline(admin.TabularInline):
    model = OrderStatusHistory
    extra = 0
    fields = ("created_at", "from_status", "to_status", "changed_by", "note")
    readonly_fields = fields
    can_delete = False
    verbose_name_plural = "Status history"

    def has_add_permission(self, request, obj=None):
        return False


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------
@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_number",
        "store",
        "customer_name",
        "status",
        "fulfilment_method",
        "payment_method",
        "payment_status",
        "items_qty",
        "total",
        "created_at",
    )
    list_filter = (
        "status",
        "fulfilment_method",
        "payment_method",
        "payment_status",
        "store",
        "created_at",
    )
    list_select_related = ("store",)
    search_fields = (
        "order_number",
        "customer_name",
        "customer_phone",
        "customer_email",
        "store__name",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    save_on_top = True
    inlines = [OrderItemInline, OrderStatusHistoryInline]

    # Only these can be edited by hand. Status changes go through the
    # actions below so stock, timestamps and history stay consistent.
    readonly_fields = (
        "order_number",
        "checkout_reference",
        "customer",
        "store",
        "customer_name",
        "customer_phone",
        "customer_email",
        "fulfilment_method",
        "pickup_location",
        "delivery_address",
        "status",
        "customer_note",
        "cancel_reason",
        "payment_method",
        "subtotal",
        "discount_total",
        "coupon_code",
        "delivery_fee",
        "total",
        "created_at",
        "updated_at",
        "confirmed_at",
        "completed_at",
        "cancelled_at",
    )
    fieldsets = (
        (None, {"fields": ("order_number", "status", "store", "customer")}),
        (
            "Customer",
            {"fields": ("customer_name", "customer_phone", "customer_email")},
        ),
        (
            "Fulfilment",
            {
                "fields": (
                    "fulfilment_method",
                    "pickup_location",
                    "delivery_address",
                    "customer_note",
                    "vendor_note",
                )
            },
        ),
        (
            "Payment",
            {
                "fields": (
                    "payment_method",
                    "payment_status",
                    "payment_reference",
                    "subtotal",
                    "discount_total",
                    "coupon_code",
                    "delivery_fee",
                    "total",
                )
            },
        ),
        (
            "Timeline",
            {
                "classes": ("collapse",),
                "fields": (
                    "checkout_reference",
                    "created_at",
                    "confirmed_at",
                    "completed_at",
                    "cancelled_at",
                    "cancel_reason",
                    "updated_at",
                ),
            },
        ),
    )
    actions = [
        "mark_confirmed",
        "mark_preparing",
        "mark_ready",
        "mark_completed",
        "mark_rejected",
        "mark_cancelled",
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(items_qty_total=Sum("items__quantity"))

    @admin.display(description="Items", ordering="items_qty_total")
    def items_qty(self, obj):
        return obj.items_qty_total or 0  # type: ignore

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        # Deleting would bypass stock release; cancel the order instead.
        return False

    # -- status actions -----------------------------------------------------
    def _transition(self, request, queryset, new_status, note=""):
        done, failed = 0, []
        for order in queryset:
            try:
                order.change_status(new_status, by=request.user, note=note)
                done += 1
            except ValidationError as exc:
                failed.append(f"{order.order_number}: {' '.join(exc.messages)}")
        if done:
            self.message_user(
                request,
                f"{done} order(s) moved to “{Order.Status(new_status).label}”.",
                level=messages.SUCCESS,
            )
        for msg in failed:
            self.message_user(request, msg, level=messages.WARNING)

    @admin.action(description="Confirm selected orders")
    def mark_confirmed(self, request, queryset):
        self._transition(request, queryset, Order.Status.CONFIRMED)

    @admin.action(description="Mark as preparing")
    def mark_preparing(self, request, queryset):
        self._transition(request, queryset, Order.Status.PREPARING)

    @admin.action(description="Mark as ready for pickup / delivery")
    def mark_ready(self, request, queryset):
        self._transition(request, queryset, Order.Status.READY)

    @admin.action(description="Mark as completed (deducts stock)")
    def mark_completed(self, request, queryset):
        self._transition(request, queryset, Order.Status.COMPLETED)

    @admin.action(description="Reject selected orders (releases stock)")
    def mark_rejected(self, request, queryset):
        self._transition(
            request, queryset, Order.Status.REJECTED, note="Rejected by admin."
        )

    @admin.action(description="Cancel selected orders (releases stock)")
    def mark_cancelled(self, request, queryset):
        self._transition(
            request, queryset, Order.Status.CANCELLED, note="Cancelled by admin."
        )


# ---------------------------------------------------------------------------
# Cart (support / debugging only)
# ---------------------------------------------------------------------------
class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    fields = ("variant", "quantity", "unit_price", "line_total", "is_available")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="Unit price")
    def unit_price(self, obj):
        return obj.unit_price

    @admin.display(description="Line total")
    def line_total(self, obj):
        return obj.line_total

    @admin.display(description="Available", boolean=True)
    def is_available(self, obj):
        return obj.is_available


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ("user", "total_items", "subtotal", "updated_at")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("user", "created_at", "updated_at")
    inlines = [CartItemInline]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("user")
            .prefetch_related("items__variant__product")
        )

    def has_add_permission(self, request):
        return False