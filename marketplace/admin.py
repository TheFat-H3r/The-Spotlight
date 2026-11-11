from django.contrib import admin
from .models import Category, Store, BannerSlot
from .models import BusinessType
 
 
@admin.register(BusinessType)
class BusinessTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "mode", "booking_style", "display_order", "is_active")
    list_filter = ("mode", "booking_style", "is_active")
    list_editable = ("display_order", "is_active")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
 
admin.site.register(Category)
admin.site.register(BannerSlot)
@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ("name", "vendor", "status", "store_type", "is_featured")
    list_filter = ("status", "store_type", "is_featured")
    search_fields = ("name", "vendor__user__email")

