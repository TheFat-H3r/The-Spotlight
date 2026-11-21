from django.contrib import admin
from .models import Payout, PayoutItem, CommissionPlan, StoreSubscription, Complaint, AdminNotification, BroadcastAnnouncement

admin.site.register(Payout)
admin.site.register(PayoutItem)
@admin.register(CommissionPlan)
class CommissionPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "commission_rate", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
admin.site.register(StoreSubscription)
admin.site.register(Complaint)
@admin.register(AdminNotification)
class AdminNotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "is_read", "created_at")
    list_filter = ("is_read",)
    search_fields = ("title", "message")
@admin.register(BroadcastAnnouncement)
class BroadcastAnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "audience", "created_at")
    list_filter = ("audience",)
    search_fields = ("title", "message")
