from django.contrib import admin, messages

from .models import Rating, Review, VendorReputation


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
class HasReplyFilter(admin.SimpleListFilter):
    title = "vendor reply"
    parameter_name = "has_reply"

    def lookups(self, request, model_admin):
        return [("yes", "Replied"), ("no", "No reply yet")]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.exclude(reply_text="")
        if self.value() == "no":
            return queryset.filter(reply_text="")
        return queryset


# ---------------------------------------------------------------------------
# Review (moderation: the only thing an admin edits is the status)
# ---------------------------------------------------------------------------
class RatingInline(admin.TabularInline):
    model = Rating
    extra = 0
    fields = ("aspect", "score")
    readonly_fields = fields
    can_delete = False
    verbose_name_plural = "Aspect ratings"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "stars",
        "title",
        "store",
        "reviewed_item",
        "display_author",
        "status",
        "has_reply",
        "created_at",
    )
    list_display_links = ("id", "stars", "title")
    list_filter = (
        "status",
        "overall_rating",
        HasReplyFilter,
        "store",
        "created_at",
    )
    list_select_related = ("store", "product", "service")
    search_fields = (
        "title",
        "body",
        "author_name",
        "reply_text",
        "store__name",
        "product__name",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    save_on_top = True
    inlines = [RatingInline]
    actions = ["hide_reviews", "restore_reviews", "remove_vendor_replies"]

    # Everything except `status` is read-only: reviews are written by
    # customers, and replies by vendors, never by admins.
    readonly_fields = (
        "order_item",
        "booking",
        "store",
        "product",
        "service",
        "author",
        "author_name",
        "overall_rating",
        "title",
        "body",
        "reply_text",
        "replied_at",
        "replied_by",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        ("Moderation", {"fields": ("status",)}),
        (
            "Review",
            {"fields": ("overall_rating", "title", "body", "author", "author_name")},
        ),
        ("Verified source", {"fields": ("order_item", "booking")}),
        ("About", {"fields": ("store", "product", "service")}),
        ("Vendor reply", {"fields": ("reply_text", "replied_by", "replied_at")}),
        (
            "Timeline",
            {"classes": ("collapse",), "fields": ("created_at", "updated_at")},
        ),
    )

    # -- columns ------------------------------------------------------------
    @admin.display(description="Rating", ordering="overall_rating")
    def stars(self, obj):
        return "★" * obj.overall_rating + "☆" * (5 - obj.overall_rating)

    @admin.display(description="Reviewed")
    def reviewed_item(self, obj):
        return obj.product or obj.service or "—"

    @admin.display(description="Author")
    def display_author(self, obj):
        return obj.display_author

    @admin.display(description="Replied", boolean=True)
    def has_reply(self, obj):
        return obj.has_reply

    # -- permissions --------------------------------------------------------
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        # Hide a review instead: deleting in bulk would skip the rating recalculation.
        return False

    # -- actions (each review is saved individually so ratings are recomputed)
    def _set_status(self, request, queryset, status, label):
        count = 0
        for review in queryset.exclude(status=status):
            review.status = status
            review.save(update_fields=["status", "updated_at"])
            count += 1
        self.message_user(
            request, f"{count} review(s) {label}.", level=messages.SUCCESS
        )

    @admin.action(description="Hide selected reviews")
    def hide_reviews(self, request, queryset):
        self._set_status(request, queryset, Review.Status.HIDDEN, "hidden")

    @admin.action(description="Restore selected reviews (publish)")
    def restore_reviews(self, request, queryset):
        self._set_status(request, queryset, Review.Status.PUBLISHED, "restored")

    @admin.action(description="Remove vendor reply (inappropriate content)")
    def remove_vendor_replies(self, request, queryset):
        count = 0
        for review in queryset.exclude(reply_text=""):
            review.remove_reply()
            count += 1
        self.message_user(
            request, f"{count} vendor reply(ies) removed.", level=messages.SUCCESS
        )


# ---------------------------------------------------------------------------
# VendorReputation (computed; view-only, with a recalculate action)
# ---------------------------------------------------------------------------
@admin.register(VendorReputation)
class VendorReputationAdmin(admin.ModelAdmin):
    list_display = (
        "vendor",
        "rating_average",
        "rating_count",
        "positive",
        "response",
        "last_review_at",
    )
    list_select_related = ("vendor",)
    search_fields = ("vendor__user__username", "vendor__user__email")
    ordering = ("-rating_average", "-rating_count")
    actions = ["recalculate"]
    readonly_fields = (
        "vendor",
        "rating_average",
        "rating_count",
        "distribution",
        "aspect_averages",
        "reply_count",
        "positive",
        "response",
        "last_review_at",
        "updated_at",
    )

    @admin.display(description="Positive (4–5★)")
    def positive(self, obj):
        return f"{obj.positive_percent}%"

    @admin.display(description="Reply rate")
    def response(self, obj):
        return f"{obj.response_rate}%"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Recalculate from published reviews")
    def recalculate(self, request, queryset):
        for reputation in queryset.select_related("vendor"):
            VendorReputation.refresh(reputation.vendor)
        self.message_user(
            request,
            f"Recalculated {queryset.count()} vendor reputation(s).",
            level=messages.SUCCESS,
        )