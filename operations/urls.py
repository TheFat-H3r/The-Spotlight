from django.urls import path
from .views import admin_home, admin_settings, authorize_stores, complaint_form, complaints, manage_bookings, manage_catalog, manage_categories, manage_orders, manage_payouts, manage_reviews, manage_stores, manage_users, marketing, marketing_ad_form, marketing_announcement_form, notifications_center, payout_detail

app_name = "operations"
urlpatterns = [
    # Workspace
    path("", admin_home, name="admin-home"),

    # Approvals & Moderation
    path("stores/authorize/", authorize_stores, name="authorize-stores"),

    # complaints
    path("complaints/", complaints, name="complaints"),
    path("complaints/add/", complaint_form, name="complaint-add"),
    path("complaints/<int:pk>/edit/", complaint_form, name="complaint-edit"),

    # Marketing
    path("marketing/", marketing, name="marketing"),
    path("marketing/ads/add/", marketing_ad_form, name="marketing-ad-add"),
    path("marketing/ads/<int:pk>/edit/", marketing_ad_form, name="marketing-ad-edit"),
    path("marketing/announcements/add/", marketing_announcement_form, name="marketing-announcement-add"),
    path("marketing/announcements/<int:pk>/edit/", marketing_announcement_form, name="marketing-announcement-edit"),

    # Marketplace & Directory
    path("stores/", manage_stores, name="manage-stores"),
    path("categories/", manage_categories, name="categories"),
    path("catalog/", manage_catalog, name="catalog"),
    path("users/", manage_users, name="manage-users"),

    # Transactions & Payouts
    path("orders/", manage_orders, name="orders"),
    path("bookings/", manage_bookings, name="bookings"),
    path("payouts/", manage_payouts, name="payouts"),
    path("payouts/<int:pk>/", payout_detail, name="payout-detail"),

    # System & Communications
    path("notifications/", notifications_center, name="notifications"),
    path("reviews/", manage_reviews, name="reviews"),
    path("settings/", admin_settings, name="admin-settings"),
]