from django.urls import path
from . import views

app_name = "shopkeeper"

urlpatterns = [
    # Overview & Notifications
    path("", views.home, name="home"),
    path("analytics/", views.analytics_reports, name="analytics"),

    # Notifications
    path("notifications/", views.notifications_list, name="notifications"),
    path("notifications/mark-all-read/", views.notification_mark_all_read, name="notification_mark_all_read"),
    path("notifications/<int:pk>/read/", views.notification_mark_read, name="notification_mark_read"),
    path("notifications/<int:pk>/delete/", views.notification_delete, name="notification_delete"),

    # My Store
    path("store/profile/", views.store_profile, name="store_profile"),
    path("store/settings/", views.store_settings, name="store_settings"),
    path("store/verification/", views.business_verification, name="store_verification"),

    # Products
    path("products/", views.product_list, {"status": "all"}, name="product_list"),
    path("products/add/", views.product_create, name="product_create"),
    path("products/approvals/", views.product_list, {"status": "pending"}, name="product_approvals"),

    # Orders
    path("orders/", views.order_list, {"status": "all"}, name="order_list"),
    path("orders/pending/", views.order_list, {"status": "pending"}, name="order_pending"),
    path("orders/completed/", views.order_list, {"status": "completed"}, name="order_completed"),
    path("orders/cancelled/", views.order_list, {"status": "cancelled"}, name="order_cancelled"),
    path("orders/<str:order_number>/status/", views.order_update_status, name="order_update_status"),
    path("inventory/", views.inventory_management, name="inventory"),

    # Services
    path("services/", views.service_list, {"status": "all"}, name="service_list"),
    path("services/add/", views.service_create, name="service_create"),
    path("services/categories/", views.service_categories, name="service_categories"),
    path("services/approvals/", views.service_list, {"status": "pending"}, name="service_approvals"),

    # Bookings
    path("bookings/", views.booking_list, {"status": "all"}, name="booking_list"),
    path("bookings/pending/", views.booking_list, {"status": "pending"}, name="booking_pending"),
    path("bookings/confirmed/", views.booking_list, {"status": "confirmed"}, name="booking_confirmed"),
    path("bookings/completed/", views.booking_list, {"status": "completed"}, name="booking_completed"),
    path("bookings/cancelled/", views.booking_list, {"status": "cancelled"}, name="booking_cancelled"),
    path("bookings/<str:reference>/status/", views.booking_update_status, name="booking_update_status"),

    # Slots & Schedule
    path("schedule/slots/", views.manage_slots, name="manage_slots"),
    path("schedule/slots/create/", views.create_slots, name="create_slots"),
    path("schedule/working-hours/", views.working_hours, name="working_hours"),

    # Sales & CRM
    path("sales/", views.sales_list, name="sales"),
    path("sales/receipt/<str:sale_type>/<int:pk>/", views.sale_receipt, name="sale_receipt"),
    path("customers/", views.customers_list, name="customers"),

    # Marketing & Promotion
    path("ads/campaigns/", views.ad_campaigns, {"status": "all"}, name="ad_campaigns"),
    path("ads/create/", views.ad_create, name="ad_create"),
    path("ads/performance/", views.ad_performance, name="ad_performance"),
    path("ads/approvals/", views.ad_campaigns, {"status": "pending"}, name="ad_approvals"),
    path("promotions/", views.promotions_coupons, name="promotions"),
    path("featured/", views.featured_listings, name="featured_listings"),
    path("announcements/", views.announcements, name="announcements"),

    # Financial Management
    path("finance/earnings/", views.earnings_overview, name="earnings_overview"),
    path("finance/payouts/", views.payout_history, name="payout_history"),
    path("subscriptions/my-plan/", views.my_subscription, name="my_subscription"),
    path("subscriptions/plans/", views.available_plans, name="available_plans"),
    path("subscriptions/billing/", views.billing_history, name="billing_history"),
    path("subscriptions/invoices/", views.invoices_list, name="invoices"),
    path("finance/transactions/", views.transactions_list, name="transactions"),

    # Reviews
    path("reviews/", views.reviews_list, name="reviews"),
    path("reviews/<int:pk>/reply/", views.review_reply, name="review_reply"),
    path("support/", views.help_support, name="support"),
]