from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ActionForm
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import CustomerProfile, User, VendorApplication, VendorProfile


def _can_review(user):
    """Only superusers and platform admins may review vendors."""
    return user.is_superuser or getattr(user, "is_platform_admin", False)


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
class CustomerProfileInline(admin.StackedInline):
    model = CustomerProfile
    can_delete = False
    extra = 0


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ("-date_joined",)
    list_display = (
        "email",
        "full_name",
        "role",
        "auth_provider",
        "is_email_verified",
        "is_active",
        "date_joined",
    )
    list_filter = ("role", "auth_provider", "is_email_verified", "is_active", "is_staff")
    search_fields = ("email", "full_name", "phone", "student_id")
    readonly_fields = ("auth_provider", "google_id", "date_joined", "last_login")
    filter_horizontal = ("groups", "user_permissions")
    inlines = [CustomerProfileInline]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("full_name", "phone", "avatar", "student_id")}),
        (
            "Role & sign-in",
            {"fields": ("role", "auth_provider", "google_id", "is_email_verified")},
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Dates", {"fields": ("date_joined", "last_login")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "full_name", "role", "password1", "password2"),
            },
        ),
    )


# ---------------------------------------------------------------------------
# Vendor profile
# ---------------------------------------------------------------------------
@admin.register(VendorProfile)
class VendorProfileAdmin(admin.ModelAdmin):
    list_display = (
        "business_name",
        "user",
        "is_verified",
        "status",
        "rating_average",
        "rating_count",
        "created_at",
    )
    list_filter = ("status", "is_verified")
    search_fields = ("business_name", "user__email", "user__full_name")
    prepopulated_fields = {"slug": ("business_name",)}
    readonly_fields = (
        "verified_at",
        "rating_average",
        "rating_count",
        "created_at",
        "updated_at",
    )
    autocomplete_fields = ()
    actions = ["suspend_vendors", "reactivate_vendors"]

    @admin.action(description="Suspend selected vendors")
    def suspend_vendors(self, request, queryset):
        if not _can_review(request.user):
            self.message_user(request, "You do not have permission.", messages.ERROR)
            return
        n = queryset.update(status=VendorProfile.Status.SUSPENDED)
        self.message_user(request, f"{n} vendor(s) suspended.", messages.SUCCESS)

    @admin.action(description="Reactivate selected vendors")
    def reactivate_vendors(self, request, queryset):
        if not _can_review(request.user):
            self.message_user(request, "You do not have permission.", messages.ERROR)
            return
        n = queryset.update(status=VendorProfile.Status.ACTIVE)
        self.message_user(request, f"{n} vendor(s) reactivated.", messages.SUCCESS)


# ---------------------------------------------------------------------------
# Vendor application (review queue)
# ---------------------------------------------------------------------------
class RejectActionForm(ActionForm):
    """Adds a reason box next to the action dropdown (used by 'Reject')."""

    rejection_reason = forms.CharField(
        required=False,
        label="Rejection reason",
        widget=forms.TextInput(attrs={"placeholder": "Required when rejecting"}),
    )


@admin.register(VendorApplication)
class VendorApplicationAdmin(admin.ModelAdmin):
    action_form = RejectActionForm
    actions = ["approve_applications", "reject_applications"]

    list_display = (
        "business_name",
        "applicant",
        "business_type",
        "status",
        "submitted_at",
        "reviewed_by",
    )
    list_filter = ("status", "business_type")
    search_fields = ("business_name", "applicant__email", "applicant__full_name")
    date_hierarchy = "submitted_at"
    ordering = ("-submitted_at",)

    # Status changes must go through the actions so roles/profiles stay in sync.
    readonly_fields = (
        "applicant",
        "status",
        "rejection_reason",
        "reviewed_by",
        "reviewed_at",
        "submitted_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Application",
            {
                "fields": (
                    "applicant",
                    "business_name",
                    "business_type",
                    "description",
                    "contact_phone",
                    "proof_document",
                    "submitted_at",
                )
            },
        ),
        (
            "Review",
            {
                "fields": (
                    "status",
                    "rejection_reason",
                    "admin_notes",
                    "reviewed_by",
                    "reviewed_at",
                )
            },
        ),
    )

    def has_add_permission(self, request):
        # Applications are submitted by users through the API, not created here.
        return False

    @admin.action(description="Approve selected applications")
    def approve_applications(self, request, queryset):
        if not _can_review(request.user):
            self.message_user(request, "You do not have permission.", messages.ERROR)
            return

        approved, skipped = 0, 0
        for application in queryset.select_related("applicant"):
            try:
                application.approve(request.user)
                approved += 1
            except ValueError:
                skipped += 1

        if approved:
            self.message_user(
                request, f"{approved} application(s) approved.", messages.SUCCESS
            )
        if skipped:
            self.message_user(
                request,
                f"{skipped} skipped (not pending).",
                messages.WARNING,
            )

    @admin.action(description="Reject selected applications (enter a reason above)")
    def reject_applications(self, request, queryset):
        if not _can_review(request.user):
            self.message_user(request, "You do not have permission.", messages.ERROR)
            return

        reason = request.POST.get("rejection_reason", "").strip()
        if not reason:
            self.message_user(
                request,
                "Enter a rejection reason in the box next to the action menu.",
                messages.ERROR,
            )
            return

        rejected, skipped = 0, 0
        for application in queryset:
            try:
                application.reject(request.user, reason)
                rejected += 1
            except ValueError:
                skipped += 1

        if rejected:
            self.message_user(
                request, f"{rejected} application(s) rejected.", messages.SUCCESS
            )
        if skipped:
            self.message_user(
                request,
                f"{skipped} skipped (not pending).",
                messages.WARNING,
            )