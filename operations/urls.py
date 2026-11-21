from django.urls import path
from .views import admin_home, admin_settings, authorize_ads, authorize_stores, complaints_list, manage_bookings, manage_catalog, manage_categories, manage_orders, manage_payouts, manage_reviews, manage_stores, manage_users, notifications_center

app_name = "operations"
urlpatterns = [
    # Workspace
    path("", admin_home, name="admin-home"),

    # Approvals & Moderation
    path("stores/authorize/", authorize_stores, name="authorize-stores"),
    path("ads/authorize/", authorize_ads, name="authorize-ads"),
    path("complaints/", complaints_list, name="complaints"),

    # Marketplace & Directory
    path("stores/", manage_stores, name="manage-stores"),
    path("categories/", manage_categories, name="categories"),
    path("catalog/", manage_catalog, name="catalog"),
    path("users/", manage_users, name="manage-users"),

    # Transactions & Payouts
    path("orders/", manage_orders, name="orders"),
    path("bookings/", manage_bookings, name="bookings"),
    path("payouts/", manage_payouts, name="payouts"),

    # System & Communications
    path("notifications/", notifications_center, name="notifications"),
    path("reviews/", manage_reviews, name="reviews"),
    path("settings/", admin_settings, name="admin-settings"),
]