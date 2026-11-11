from django import forms
from django.contrib import admin, messages
from django.db.models import Count, F, Q, Sum
from django.utils import timezone
from django.utils.html import format_html

from .models import Inventory, Product, ProductImage, Variant


# ---------------------------------------------------------------------------
# Inlines (shown on the Product page)
# ---------------------------------------------------------------------------
class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0
    fields = ("preview", "image", "alt_text", "variant", "is_primary", "display_order")
    readonly_fields = ("preview",)

    @admin.display(description="Preview")
    def preview(self, obj):
        if obj.pk and obj.image:
            return format_html(
                '<img src="{}" style="height:48px;border-radius:4px;" />', obj.image.url
            )
        return "—"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # Only offer variants that belong to the product being edited.
        if db_field.name == "variant":
            assert request.resolver_match is not None
            product_id = request.resolver_match.kwargs.get("object_id")
            kwargs["queryset"] = Variant.objects.filter(product_id=product_id)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class VariantInline(admin.TabularInline):
    model = Variant
    extra = 0
    fields = (
        "name",
        "sku",
        "price",
        "attributes",
        "is_active",
        "display_order",
        "is_default",
        "stock",
    )
    readonly_fields = ("is_default", "stock")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("inventory", "product")

    @admin.display(description="Stock")
    def stock(self, obj):
        inv = getattr(obj, "inventory", None) if obj.pk else None
        if inv is None:
            return "—"
        if not inv.track_stock:
            return "Not tracked"
        return f"{inv.available} available ({inv.reserved_quantity} reserved)"


# ---------------------------------------------------------------------------
# Product
# ---------------------------------------------------------------------------
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "thumbnail",
        "name",
        "store",
        "category",
        "price",
        "status",
        "is_featured",
        "stock_display",
        "rating_average",
        "sold_count",
        "created_at",
    )
    list_display_links = ("thumbnail", "name")
    list_editable = ("status", "is_featured")
    list_filter = ("status", "is_featured", "condition", "category", "store")
    list_select_related = ("store", "category")
    search_fields = ("name", "slug", "store__name", "variants__sku")
    date_hierarchy = "created_at"
    readonly_fields = (
        "slug",
        "rating_average",
        "rating_count",
        "sold_count",
        "view_count",
        "created_at",
        "updated_at",
    )
    inlines = [VariantInline, ProductImageInline]
    save_on_top = True
    actions = [
        "publish",
        "archive",
        "hide_from_public",
        "feature",
        "unfeature",
    ]

    fieldsets = (
        (None, {"fields": ("store", "category", "name", "slug")}),
        (
            "Details",
            {"fields": ("short_description", "description", "condition", "tags")},
        ),
        ("Pricing", {"fields": ("price", "compare_at_price")}),
        ("Visibility & moderation", {"fields": ("status", "is_featured")}),
        (
            "Stats",
            {
                "classes": ("collapse",),
                "fields": (
                    "rating_average",
                    "rating_count",
                    "sold_count",
                    "view_count",
                    "created_at",
                    "updated_at",
                ),
            },
        ),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .prefetch_related("images")
            .annotate(
                available_total=Sum(
                    F("variants__inventory__quantity")
                    - F("variants__inventory__reserved_quantity"),
                    filter=Q(variants__is_active=True),
                ),
                untracked_count=Count(
                    "variants",
                    filter=Q(
                        variants__is_active=True,
                        variants__inventory__track_stock=False,
                    ),
                ),
            )
        )

    # -- columns ------------------------------------------------------------
    @admin.display(description="")
    def thumbnail(self, obj):
        image = obj.primary_image
        if image and image.image:
            return format_html(
                '<img src="{}" style="height:36px;width:36px;object-fit:cover;'
                'border-radius:4px;" />',
                image.image.url,
            )
        return "—"

    @admin.display(description="Stock", ordering="available_total")
    def stock_display(self, obj):
        if obj.untracked_count:  # type: ignore
            return "Made to order"
        total = obj.available_total or 0  # type: ignore
        if total <= 0:
            return format_html('<span style="color:#c0392b;">Out of stock</span>')
        return total

    # -- moderation actions -------------------------------------------------
    def _set_status(self, request, queryset, status, label):
        count = queryset.update(status=status, updated_at=timezone.now())
        self.message_user(
            request, f"{count} product(s) {label}.", level=messages.SUCCESS
        )

    @admin.action(description="Publish selected products")
    def publish(self, request, queryset):
        self._set_status(request, queryset, Product.Status.ACTIVE, "published")

    @admin.action(description="Archive selected products")
    def archive(self, request, queryset):
        self._set_status(request, queryset, Product.Status.ARCHIVED, "archived")

    @admin.action(description="Hide selected products (moderation)")
    def hide_from_public(self, request, queryset):
        self._set_status(request, queryset, Product.Status.HIDDEN, "hidden")

    @admin.action(description="Feature selected products")
    def feature(self, request, queryset):
        count = queryset.update(is_featured=True, updated_at=timezone.now())
        self.message_user(request, f"{count} product(s) featured.")

    @admin.action(description="Remove featured flag")
    def unfeature(self, request, queryset):
        count = queryset.update(is_featured=False, updated_at=timezone.now())
        self.message_user(request, f"{count} product(s) unfeatured.")


# ---------------------------------------------------------------------------
# Inventory (rows are created automatically with each variant)
# ---------------------------------------------------------------------------
class InventoryAdminForm(forms.ModelForm):
    class Meta:
        model = Inventory
        fields = "__all__"

    def clean(self):
        data = super().clean()
        assert data is not None
        quantity = data.get("quantity")
        reserved = data.get("reserved_quantity")
        if quantity is not None and reserved is not None and reserved > quantity:
            raise forms.ValidationError(
                "Reserved units cannot exceed the quantity on hand."
            )
        return data


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    form = InventoryAdminForm
    list_display = (
        "variant",
        "store",
        "track_stock",
        "quantity",
        "reserved_quantity",
        "available",
        "low_stock",
        "updated_at",
    )
    list_filter = ("track_stock", "variant__product__status", "variant__product__store")
    list_select_related = ("variant", "variant__product", "variant__product__store")
    search_fields = ("variant__name", "variant__sku", "variant__product__name")
    readonly_fields = ("variant", "available", "updated_at")
    ordering = ("variant__product__name", "variant__name")

    @admin.display(description="Store", ordering="variant__product__store__name")
    def store(self, obj):
        return obj.variant.product.store

    @admin.display(description="Available")
    def available(self, obj):
        return obj.available

    @admin.display(description="Low stock", boolean=True)
    def low_stock(self, obj):
        return obj.is_low_stock

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False