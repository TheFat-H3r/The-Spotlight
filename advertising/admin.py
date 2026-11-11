from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.utils.html import format_html

from .models import (
    Coupon,
    CouponRedemption,
    FeaturedItem,
    PromoBanner,
    PromoStatus,
    SponsoredListing,
)


def _thumb(image, size=40):
    if image:
        return format_html(
            '<img src="{}" style="height:{}px;max-width:120px;object-fit:cover;'
            'border-radius:4px;" />',
            image.url,
            size,
        )
    return "—"


# ---------------------------------------------------------------------------
# Shared behaviour
# ---------------------------------------------------------------------------
class RecordCreatorMixin:
    """Remember which staff member created a record."""

    def save_model(self, request, obj, form, change):
        if not change and getattr(obj, "created_by_id", None) is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)  # type: ignore


class ApprovalActionsMixin:
    """
    approve / reject / pause / resume for SponsoredListing and PromoBanner.
    These call the model methods, so rules such as "banner slot is full"
    are enforced. Status itself is read-only on the form for the same reason.
    """

    def _run(self, request, queryset, action, verb):
        done, problems = 0, []
        for obj in queryset:
            try:
                action(obj)
                done += 1
            except ValidationError as exc:
                problems.append(f"{obj}: {' '.join(exc.messages)}")
        if done:
            self.message_user(  # type: ignore
                request, f"{done} item(s) {verb}.", level=messages.SUCCESS
            )
        for problem in problems:
            self.message_user(request, problem, level=messages.WARNING)  # type: ignore

    @admin.action(description="Approve selected")
    def approve_selected(self, request, queryset):
        self._run(
            request,
            queryset.exclude(status=PromoStatus.ACTIVE),
            lambda o: o.approve(request.user),
            "approved",
        )

    @admin.action(description="Reject selected")
    def reject_selected(self, request, queryset):
        # Use the "Rejection reason" field on the item to explain it to the vendor.
        self._run(
            request,
            queryset.exclude(status=PromoStatus.REJECTED),
            lambda o: o.reject(request.user, o.rejection_reason or "Rejected by admin."),
            "rejected",
        )

    @admin.action(description="Pause selected")
    def pause_selected(self, request, queryset):
        self._run(request, queryset, lambda o: o.pause(), "paused")

    @admin.action(description="Resume selected")
    def resume_selected(self, request, queryset):
        self._run(request, queryset, lambda o: o.resume(), "resumed")

    @admin.display(description="State")
    def state_display(self, obj):
        return obj.state

    @admin.display(description="CTR %")
    def ctr_display(self, obj):
        return obj.ctr


APPROVAL_ACTIONS = [
    "approve_selected",
    "reject_selected",
    "pause_selected",
    "resume_selected",
]
STATS_FIELDS = ("impressions", "clicks", "ctr_display")
AUDIT_FIELDS = (
    "reviewed_by",
    "reviewed_at",
    "created_by",
    "created_at",
    "updated_at",
)


# ---------------------------------------------------------------------------
# SponsoredListing
# ---------------------------------------------------------------------------
@admin.register(SponsoredListing)
class SponsoredListingAdmin(RecordCreatorMixin, ApprovalActionsMixin, admin.ModelAdmin):
    list_display = (
        "target_display",
        "target_type",
        "store",
        "placement",
        "status",
        "state_display",
        "weight",
        "fee",
        "starts_at",
        "ends_at",
        "impressions",
        "clicks",
        "ctr_display",
    )
    list_display_links = ("target_display",)
    list_filter = ("status", "placement", "store", "starts_at")
    list_select_related = ("store", "product", "service")
    search_fields = ("store__name", "product__name", "payment_reference")
    date_hierarchy = "starts_at"
    save_on_top = True
    actions = APPROVAL_ACTIONS
    readonly_fields = ("status", "state_display", *STATS_FIELDS, *AUDIT_FIELDS)
    fieldsets = (
        (None, {"fields": ("store", "product", "service")}),
        ("Placement", {"fields": ("placement", "category", "keywords", "weight")}),
        ("Schedule", {"fields": ("starts_at", "ends_at")}),
        ("Payment", {"fields": ("fee", "payment_reference")}),
        (
            "Approval",
            {"fields": ("status", "state_display", "rejection_reason", "reviewed_by", "reviewed_at")},
        ),
        ("Performance", {"fields": STATS_FIELDS}),
        ("Audit", {"classes": ("collapse",), "fields": ("created_by", "created_at", "updated_at")}),
    )

    @admin.display(description="Promoting")
    def target_display(self, obj):
        return str(obj.target)


# ---------------------------------------------------------------------------
# PromoBanner
# ---------------------------------------------------------------------------
@admin.register(PromoBanner)
class PromoBannerAdmin(RecordCreatorMixin, ApprovalActionsMixin, admin.ModelAdmin):
    list_display = (
        "preview",
        "title",
        "slot",
        "owner",
        "status",
        "state_display",
        "display_order",
        "starts_at",
        "ends_at",
        "impressions",
        "clicks",
        "ctr_display",
    )
    list_display_links = ("preview", "title")
    list_filter = ("status", "slot", "store", "starts_at")
    list_select_related = ("slot", "store")
    search_fields = ("title", "subtitle", "store__name", "slot__code")
    date_hierarchy = "starts_at"
    save_on_top = True
    actions = APPROVAL_ACTIONS
    readonly_fields = (
        "status",
        "state_display",
        "large_preview",
        "image_width",
        "image_height",
        *STATS_FIELDS,
        *AUDIT_FIELDS,
    )
    fieldsets = (
        (None, {"fields": ("slot", "store", "title", "subtitle", "cta_label", "link_url")}),
        (
            "Images",
            {
                "fields": (
                    "image",
                    "large_preview",
                    "image_width",
                    "image_height",
                    "mobile_image",
                    "alt_text",
                )
            },
        ),
        ("Schedule", {"fields": ("display_order", "starts_at", "ends_at")}),
        ("Payment", {"fields": ("fee", "payment_reference")}),
        (
            "Approval",
            {"fields": ("status", "state_display", "rejection_reason", "reviewed_by", "reviewed_at")},
        ),
        ("Performance", {"fields": STATS_FIELDS}),
        ("Audit", {"classes": ("collapse",), "fields": ("created_by", "created_at", "updated_at")}),
    )

    @admin.display(description="")
    def preview(self, obj):
        return _thumb(obj.image, 36)

    @admin.display(description="Preview")
    def large_preview(self, obj):
        return _thumb(obj.image, 120) if obj.pk else "Save to see a preview."

    @admin.display(description="Owner", ordering="store__name")
    def owner(self, obj):
        return obj.store or "Platform"


# ---------------------------------------------------------------------------
# FeaturedItem
# ---------------------------------------------------------------------------
@admin.register(FeaturedItem)
class FeaturedItemAdmin(RecordCreatorMixin, admin.ModelAdmin):
    list_display = (
        "title_display",
        "section",
        "position",
        "is_active",
        "starts_at",
        "ends_at",
        "impressions",
        "clicks",
    )
    list_display_links = ("title_display",)
    list_editable = ("position", "is_active")
    list_filter = ("section", "is_active", "starts_at")
    list_select_related = ("product", "service", "store", "venture")
    search_fields = ("custom_title", "product__name", "store__name")
    save_on_top = True
    actions = ["activate", "deactivate"]
    readonly_fields = ("impressions", "clicks", "created_by", "created_at", "updated_at")
    fieldsets = (
        (
            "What to feature",
            {
                "description": "Fill in exactly one target, matching the section.",
                "fields": ("section", "product", "service", "store", "venture"),
            },
        ),
        ("Editorial overrides", {"fields": ("custom_title", "custom_blurb", "image")}),
        ("Display", {"fields": ("position", "is_active", "starts_at", "ends_at")}),
        ("Performance", {"fields": ("impressions", "clicks")}),
        ("Audit", {"classes": ("collapse",), "fields": ("created_by", "created_at", "updated_at")}),
    )

    @admin.display(description="Featured")
    def title_display(self, obj):
        return obj.title

    @admin.action(description="Activate selected")
    def activate(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f"{count} item(s) activated.", level=messages.SUCCESS)

    @admin.action(description="Deactivate selected")
    def deactivate(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f"{count} item(s) deactivated.", level=messages.SUCCESS)


# ---------------------------------------------------------------------------
# Coupon
# ---------------------------------------------------------------------------
class CouponRedemptionInline(admin.TabularInline):
    model = CouponRedemption
    extra = 0
    fields = ("order", "user", "discount_amount", "created_at")
    readonly_fields = fields
    can_delete = False
    verbose_name_plural = "Redemptions"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Coupon)
class CouponAdmin(RecordCreatorMixin, admin.ModelAdmin):
    list_display = (
        "code",
        "label",
        "scope",
        "is_active",
        "live",
        "usage",
        "valid_from",
        "valid_until",
    )
    list_display_links = ("code",)
    list_editable = ("is_active",)
    list_filter = ("is_active", "discount_type", "first_order_only", "store")
    list_select_related = ("store",)
    search_fields = ("code", "description", "store__name")
    date_hierarchy = "created_at"
    save_on_top = True
    inlines = [CouponRedemptionInline]
    actions = ["activate", "deactivate"]
    readonly_fields = ("times_used", "created_by", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("code", "description", "store")}),
        ("Discount", {"fields": ("discount_type", "value", "max_discount", "min_order_amount")}),
        (
            "Limits",
            {"fields": ("usage_limit", "per_user_limit", "first_order_only", "times_used")},
        ),
        ("Validity", {"fields": ("is_active", "valid_from", "valid_until")}),
        ("Audit", {"classes": ("collapse",), "fields": ("created_by", "created_at", "updated_at")}),
    )

    @admin.display(description="Applies to", ordering="store__name")
    def scope(self, obj):
        return obj.store or "Platform-wide"

    @admin.display(description="Live now", boolean=True)
    def live(self, obj):
        return obj.is_live and not obj.is_exhausted

    @admin.display(description="Used")
    def usage(self, obj):
        limit = obj.usage_limit if obj.usage_limit is not None else "∞"
        return f"{obj.times_used} / {limit}"

    @admin.action(description="Activate selected coupons")
    def activate(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f"{count} coupon(s) activated.", level=messages.SUCCESS)

    @admin.action(description="Deactivate selected coupons")
    def deactivate(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f"{count} coupon(s) deactivated.", level=messages.SUCCESS)


# ---------------------------------------------------------------------------
# CouponRedemption (audit log, view-only)
# ---------------------------------------------------------------------------
@admin.register(CouponRedemption)
class CouponRedemptionAdmin(admin.ModelAdmin):
    list_display = ("coupon", "order", "user", "discount_amount", "created_at")
    list_filter = ("coupon", "created_at")
    list_select_related = ("coupon", "order", "user")
    search_fields = ("coupon__code", "order__order_number", "user__username")
    date_hierarchy = "created_at"
    readonly_fields = ("coupon", "order", "user", "discount_amount", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False