from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.utils.html import format_html

from .models import AvailabilitySlot, Booking, Service


# ---------------------------------------------------------------------------
# Inlines
# ---------------------------------------------------------------------------
class AvailabilitySlotInline(admin.TabularInline):
    model = AvailabilitySlot
    fields = ("start_at", "end_at", "capacity", "is_active")
    extra = 0
    ordering = ("-start_at",)
    show_change_link = True


class BookingInline(admin.TabularInline):
    """Read-only list of the bookings made against a slot."""

    model = Booking
    fields = ("reference", "customer", "seats", "status", "total_price", "created_at")
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "store",
        "category",
        "price",
        "price_unit",
        "duration_minutes",
        "capacity",
        "requires_approval",
        "is_active",
        "rating_average",
    )
    list_filter = (
        "is_active",
        "requires_approval",
        "price_unit",
        "location_type",
        "category",
        "store__business_type",
        "store__status",
    )
    list_editable = ("is_active",)
    list_select_related = ("store", "category")
    search_fields = ("name", "short_description", "store__name")
    prepopulated_fields = {"slug": ("name",)}
    raw_id_fields = ("store", "category")
    readonly_fields = ("rating_average", "rating_count", "created_at", "updated_at")
    date_hierarchy = "created_at"
    inlines = [AvailabilitySlotInline]
    fieldsets = (
        (None, {"fields": ("store", "category", "name", "slug")}),
        (
            "Description",
            {"fields": ("short_description", "description", "image")},
        ),
        ("Pricing", {"fields": ("price", "price_unit")}),
        (
            "Scheduling rules",
            {
                "fields": (
                    "duration_minutes",
                    "capacity",
                    "min_notice_hours",
                    "max_advance_days",
                    "cancellation_window_hours",
                    "requires_approval",
                )
            },
        ),
        ("Location", {"fields": ("location_type", "location_details")}),
        ("Visibility", {"fields": ("is_active",)}),
        (
            "Reputation (managed by reviews)",
            {"fields": ("rating_average", "rating_count"), "classes": ("collapse",)},
        ),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )


# ---------------------------------------------------------------------------
# AvailabilitySlot
# ---------------------------------------------------------------------------
@admin.register(AvailabilitySlot)
class AvailabilitySlotAdmin(admin.ModelAdmin):
    list_display = ("service", "start_at", "end_at", "seats_display", "is_active")
    list_filter = ("is_active", "service__store", "service")
    list_select_related = ("service", "service__store")
    search_fields = ("service__name", "service__store__name")
    raw_id_fields = ("service",)
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "start_at"
    inlines = [BookingInline]
    actions = ["activate_slots", "deactivate_slots"]

    def get_queryset(self, request):
        # Annotates total_seats / taken_seats so the list needs no per-row queries.
        return super().get_queryset(request).with_spots()  # type: ignore

    @admin.display(description="Seats taken")
    def seats_display(self, obj):
        taken = getattr(obj, "taken_seats", None)
        total = getattr(obj, "total_seats", None)
        if taken is None or total is None:
            return f"{obj.spots_taken}/{obj.total_capacity}"
        return f"{taken}/{total}"

    @admin.action(description="Make selected slots available")
    def activate_slots(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} slot(s) activated.", messages.SUCCESS)

    @admin.action(description="Block selected slots")
    def deactivate_slots(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} slot(s) blocked.", messages.SUCCESS)


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------
STATUS_COLOURS = {
    Booking.Status.PENDING: "#b45309",
    Booking.Status.CONFIRMED: "#15803d",
    Booking.Status.REJECTED: "#b91c1c",
    Booking.Status.CANCELLED_BY_CUSTOMER: "#6b7280",
    Booking.Status.CANCELLED_BY_VENDOR: "#6b7280",
    Booking.Status.COMPLETED: "#1d4ed8",
    Booking.Status.NO_SHOW: "#7c3aed",
}


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "customer",
        "service",
        "starts_at",
        "seats",
        "status_badge",
        "total_price",
        "created_at",
    )
    list_filter = ("status", "service__store", "created_at")
    list_select_related = ("customer", "service", "service__store", "slot")
    # Adjust the customer lookups to match the fields on your User model.
    search_fields = ("reference", "customer__email", "service__name", "service__store__name")
    raw_id_fields = ("customer", "service", "slot")
    date_hierarchy = "created_at"
    # Status is read-only so it can only change through the transition actions,
    # which enforce the rules (e.g. only pending bookings can be approved).
    readonly_fields = (
        "reference",
        "status",
        "total_price",
        "confirmed_at",
        "responded_at",
        "cancelled_at",
        "completed_at",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (None, {"fields": ("reference", "customer", "service", "slot", "seats")}),
        ("Status", {"fields": ("status", "status_reason", "total_price")}),
        (
            "Notes",
            {"fields": ("customer_note", "customer_phone", "vendor_note")},
        ),
        (
            "Transport trip",
            {"fields": ("pickup_location", "dropoff_location")},
        ),
        (
            "Timeline",
            {
                "fields": (
                    "confirmed_at",
                    "responded_at",
                    "cancelled_at",
                    "completed_at",
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )
    actions = [
        "approve_bookings",
        "reject_bookings",
        "cancel_bookings",
        "complete_bookings",
        "mark_no_show",
    ]

    # -- list columns --------------------------------------------------------
    @admin.display(description="Starts", ordering="slot__start_at")
    def starts_at(self, obj):
        return obj.slot.start_at

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        colour = STATUS_COLOURS.get(obj.status, "#6b7280")
        return format_html(
            '<strong style="color:{}">{}</strong>', colour, obj.get_status_display()
        )

    # -- actions -------------------------------------------------------------
    def _transition(self, request, queryset, method, done_label, **kwargs):
        done = 0
        bookings = queryset.select_related("service__store__vendor", "slot")
        for booking in bookings:
            try:
                getattr(booking, method)(**kwargs)
                done += 1
            except ValidationError as exc:
                self.message_user(
                    request,
                    f"{booking.reference}: {' '.join(exc.messages)}",
                    messages.WARNING,
                )
        if done:
            self.message_user(
                request, f"{done} booking(s) {done_label}.", messages.SUCCESS
            )

    @admin.action(description="Approve selected pending bookings")
    def approve_bookings(self, request, queryset):
        self._transition(request, queryset, "approve", "approved")

    @admin.action(description="Reject selected pending bookings")
    def reject_bookings(self, request, queryset):
        self._transition(
            request, queryset, "reject", "rejected", reason="Rejected by an administrator."
        )

    @admin.action(description="Cancel selected bookings (as vendor/admin)")
    def cancel_bookings(self, request, queryset):
        self._transition(
            request,
            queryset,
            "cancel_by_vendor",
            "cancelled",
            reason="Cancelled by an administrator.",
        )

    @admin.action(description="Mark selected bookings as completed")
    def complete_bookings(self, request, queryset):
        self._transition(request, queryset, "complete", "marked completed")

    @admin.action(description="Mark selected bookings as no-show")
    def mark_no_show(self, request, queryset):
        self._transition(request, queryset, "mark_no_show", "marked as no-show")