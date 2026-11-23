from django.urls import path
from .views import admin_home, admin_settings, authorize_stores, business_type_form, catalog_management, categories_management, category_form, complaint_form, complaints, manage_bookings, manage_orders, manage_payouts, manage_reviews, manage_users, marketing, marketing_ad_form, marketing_announcement_form, notifications_center, payout_detail, product_form, service_form, store_form, stores_management

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

    # Stores management
    path("stores/", stores_management, name="stores"),
    path("stores/add/", store_form, name="store-add"),
    path("stores/<int:pk>/edit/", store_form, name="store-edit"),
    
    # Categories / types
    path("categories/", categories_management, name="categories"),
    path("categories/add/", category_form, name="category-add"),
    path("categories/<int:pk>/edit/", category_form, name="category-edit"),
    path("business-types/add/", business_type_form, name="business-type-add"),
    path("business-types/<int:pk>/edit/", business_type_form, name="business-type-edit"),
    
    # Catalog (product/services)
    path("catalog/", catalog_management, name="catalog"),
    path("catalog/products/add/", product_form, name="product-add"),
    path("catalog/products/<int:pk>/edit/", product_form, name="product-edit"),
    path("catalog/services/add/", service_form, name="service-add"),
    path("catalog/services/<int:pk>/edit/", service_form, name="service-edit"),
    
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