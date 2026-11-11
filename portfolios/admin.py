from django.contrib import admin, messages
from django.db.models import Count
from django.utils.html import format_html

from .models import Achievement, GalleryImage, Project, VentureProfile


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
# Inlines (shown on the venture page)
# ---------------------------------------------------------------------------
class ProjectInline(admin.TabularInline):
    model = Project
    extra = 0
    fields = ("title", "project_type", "status", "is_featured", "is_visible", "display_order")
    show_change_link = True


class AchievementInline(admin.TabularInline):
    model = Achievement
    extra = 0
    fields = ("title", "kind", "issuer", "achieved_on", "source", "is_verified")


class GalleryImageInline(admin.TabularInline):
    model = GalleryImage
    extra = 0
    fields = ("preview", "image", "project", "caption", "display_order")
    readonly_fields = ("preview",)

    @admin.display(description="Preview")
    def preview(self, obj):
        return _thumb(obj.image, 48) if obj.pk else "—"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # Only offer projects that belong to the venture being edited.
        if db_field.name == "project":
            assert request.resolver_match is not None
            venture_id = request.resolver_match.kwargs.get("object_id")
            kwargs["queryset"] = Project.objects.filter(venture_id=venture_id)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


# ---------------------------------------------------------------------------
# VentureProfile (review queue + moderation)
# ---------------------------------------------------------------------------
@admin.register(VentureProfile)
class VentureProfileAdmin(admin.ModelAdmin):
    list_display = (
        "logo_thumb",
        "name",
        "vendor",
        "status",
        "published_at",
        "projects_count",
        "gallery_count",
        "achievements_count",
        "view_count",
        "updated_at",
    )
    list_display_links = ("logo_thumb", "name")
    list_filter = ("status", "category", "created_at")
    list_select_related = ("vendor", "category")
    search_fields = ("name", "tagline", "faculty", "store__name")
    date_hierarchy = "created_at"
    save_on_top = True
    inlines = [ProjectInline, AchievementInline, GalleryImageInline]
    actions = ["publish", "send_back", "hide"]

    # Status changes go through the actions so reviewer, timestamps and
    # published_at are always recorded.
    readonly_fields = (
        "slug",
        "status",
        "missing_info",
        "live_stats",
        "reviewed_by",
        "reviewed_at",
        "published_at",
        "view_count",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (None, {"fields": ("vendor", "store", "name", "slug", "tagline", "category")}),
        ("Story", {"fields": ("story", "logo", "cover_image")}),
        (
            "Team & links",
            {"fields": ("founded_year", "faculty", "team_members", "website", "social_links")},
        ),
        (
            "Review",
            {
                "description": "Use the actions on the list page to publish, send back or hide. "
                "Write the feedback below first when sending a venture back.",
                "fields": (
                    "status",
                    "missing_info",
                    "review_note",
                    "reviewed_by",
                    "reviewed_at",
                    "published_at",
                ),
            },
        ),
        ("Performance", {"fields": ("live_stats", "view_count")}),
        ("Audit", {"classes": ("collapse",), "fields": ("created_at", "updated_at")}),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(
                n_projects=Count("projects", distinct=True),
                n_gallery=Count("gallery", distinct=True),
                n_achievements=Count("achievements", distinct=True),
            )
        )

    # -- columns ------------------------------------------------------------
    @admin.display(description="")
    def logo_thumb(self, obj):
        return _thumb(obj.logo or obj.cover_image, 36)

    @admin.display(description="Projects", ordering="n_projects")
    def projects_count(self, obj):
        return obj.n_projects  # type: ignore

    @admin.display(description="Photos", ordering="n_gallery")
    def gallery_count(self, obj):
        return obj.n_gallery  # type: ignore

    @admin.display(description="Achievements", ordering="n_achievements")
    def achievements_count(self, obj):
        return obj.n_achievements  # type: ignore

    @admin.display(description="Missing for review")
    def missing_info(self, obj):
        if not obj.pk:
            return "—"
        missing = obj.missing_for_review()
        return ", ".join(missing) if missing else "Nothing: complete."

    @admin.display(description="Live stats")
    def live_stats(self, obj):
        if not obj.pk:
            return "—"
        stats = obj.get_stats()
        return (
            f"{stats['completed_orders']} completed orders · "
            f"{stats['active_products']} active products · "
            f"{stats['rating_average']}★ ({stats['rating_count']}) · "
            f"{stats['projects']} projects"
        )

    # -- review actions -----------------------------------------------------
    @admin.action(description="Publish selected ventures")
    def publish(self, request, queryset):
        count = 0
        for venture in queryset.exclude(status=VentureProfile.Status.PUBLISHED):
            venture.publish(by=request.user)
            count += 1
        self.message_user(request, f"{count} venture(s) published.", level=messages.SUCCESS)

    @admin.action(description="Send back to draft (uses the review note)")
    def send_back(self, request, queryset):
        count = 0
        for venture in queryset.exclude(status=VentureProfile.Status.DRAFT):
            venture.send_back(
                by=request.user,
                note=venture.review_note or "Please review your page and resubmit.",
            )
            count += 1
        self.message_user(request, f"{count} venture(s) sent back.", level=messages.SUCCESS)

    @admin.action(description="Hide selected ventures (moderation)")
    def hide(self, request, queryset):
        count = 0
        for venture in queryset.exclude(status=VentureProfile.Status.HIDDEN):
            venture.hide(
                by=request.user, note=venture.review_note or "Hidden by an administrator."
            )
            count += 1
        self.message_user(request, f"{count} venture(s) hidden.", level=messages.SUCCESS)


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------
@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        "thumb",
        "title",
        "venture",
        "project_type",
        "status",
        "is_featured",
        "is_visible",
        "display_order",
        "completed_on",
    )
    list_display_links = ("thumb", "title")
    list_editable = ("is_featured", "is_visible", "display_order")
    list_filter = ("project_type", "status", "is_featured", "is_visible", "venture")
    list_select_related = ("venture",)
    search_fields = ("title", "summary", "collaborators", "venture__name")
    readonly_fields = ("slug", "created_at", "updated_at")
    actions = ["show", "hide"]

    @admin.display(description="")
    def thumb(self, obj):
        return _thumb(obj.cover_image, 36)

    @admin.action(description="Show selected projects")
    def show(self, request, queryset):
        count = queryset.update(is_visible=True)
        self.message_user(request, f"{count} project(s) shown.", level=messages.SUCCESS)

    @admin.action(description="Hide selected projects")
    def hide(self, request, queryset):
        count = queryset.update(is_visible=False)
        self.message_user(request, f"{count} project(s) hidden.", level=messages.SUCCESS)


# ---------------------------------------------------------------------------
# Achievement (verification queue)
# ---------------------------------------------------------------------------
@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "venture",
        "kind",
        "issuer",
        "achieved_on",
        "source",
        "is_verified",
    )
    list_filter = ("is_verified", "kind", "source")
    list_select_related = ("venture",)
    search_fields = ("title", "issuer", "description", "venture__name")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "updated_at")
    actions = ["verify", "unverify"]

    @admin.action(description="Mark as verified")
    def verify(self, request, queryset):
        count = queryset.update(is_verified=True)
        self.message_user(request, f"{count} achievement(s) verified.", level=messages.SUCCESS)

    @admin.action(description="Remove verification (self-reported only)")
    def unverify(self, request, queryset):
        # Platform-earned achievements are always verified, so leave those alone.
        count = queryset.exclude(source=Achievement.Source.PLATFORM).update(is_verified=False)
        self.message_user(request, f"{count} achievement(s) unverified.", level=messages.SUCCESS)