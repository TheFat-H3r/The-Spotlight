from .views import (
    RegisterView, LoginView, PasswordResetConfirmView, PasswordResetRequestView,
    ProfileView, ResendVerificationEmailView, VerifyEmailConfirmView,
    advertisement_list, advertisement_create, advertisement_delete, advertisement_detail, advertisement_update,
    announcement_create, announcement_delete, announcement_detail, announcement_list, announcement_update,
    home, about, contact, faq, privacy, report, terms,
    login_view, logout_view, create_account, user_settings, user_profile, become_vendor,
    product_list, product_detail, category_detail,
    service_list, service_detail, store_list, store_detail, flash_sale,
    cart_detail, clear_cart, delete_cart_item, remove_cart_item, add_to_cart, update_cart, update_cart_item,
    wishlist, checkout, order_detail,
    create_booking, cancel_customer_booking, delete_customer_booking, customer_bookings_list,
    cancel_customer_order, delete_customer_order, customer_orders_list,
    owner_bookings_list, owner_orders_list,
    update_booking_status, update_order_status,
)

from django.urls import path

app_name = 'core'

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path('verify/<str:token>/', VerifyEmailConfirmView.as_view(), name='verify_email_confirm'),
    path('resend-verification/', ResendVerificationEmailView.as_view(), name='resend_verification'),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", logout_view, name="logout"),
    path('profile/', ProfileView.as_view(), name='user_profile'),
    path('password-reset/', PasswordResetRequestView.as_view(), name='password_reset'),
    path('password-reset/confirm/<str:token>/', PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('user-settings/', user_settings, name='user-settings'),
    
    # Main & Static Pages
    path('', home, name='home'),
    path('about/', about, name='about'),
    path('contact/', contact, name='contact'),
    path('faq/', faq, name='faq'),
    path('report/<slug:slug>/<slug:store>', report, name='report'),
    path('privacy-policy/', privacy, name='privacy'),
    path('terms-of-service/', terms, name='terms'),

    # Authentication & User Account
    path('become-vendor/', become_vendor, name='become_vendor'),

    # Catalog: Products, Services & Stores
    path('flash-sales/', product_list, name='flash_sale_list'),
    path('products/', product_list, name='product_list'),
    path('products/<slug:slug>/', product_detail, name='product_detail'),
    path('categories/', category_detail, name='category_list'),
    path('category/<slug:slug>/', category_detail, name='category_detail'),
    path('services/', service_list, name='service_list'),
    path('services/<slug:slug>/', service_detail, name='service_detail'),
    path('stores/', store_list, name='store_list'),
    path('stores/<slug:slug>/', store_detail, name='store_detail'),
    path('flash-sale/', flash_sale, name='flash_sale'),

    # Shopping & Orders
    path('services/<slug:service_slug>/<slug:store_slug>/booking/new/', create_booking, name='create-booking'),
    path("cart/", cart_detail, name="cart"),
    path("cart/add/<slug:slug>/", add_to_cart, name="add_to_cart"),
    path("cart/update/<int:item_id>/", update_cart,  name="update_cart"),
    path("cart/delete/<int:item_id>/", delete_cart_item, name="delete_cart_item"),
    path("cart/clear/", clear_cart, name="clear_cart"),
    path('wishlist/', wishlist, name='wishlist'),
    path('checkout/', checkout, name='checkout'),
    path('orders/<int:order_id>/', order_detail, name='order_detail'),

    path('ads/', advertisement_list, name='advertisement-list'),
    path('ads/create/', advertisement_create, name='advertisement-create'),
    path('ads/<slug:slug>/', advertisement_detail, name='advertisement-detail'),
    path('ads/<slug:slug>/edit/', advertisement_update, name='advertisement-update'),
    path('ads/<slug:slug>/delete/', advertisement_delete, name='advertisement-delete'),

    # Announcement URLs
    path('announcements/', announcement_list, name='announcement-list'),
    path('announcements/create/', announcement_create, name='announcement-create'),
    path('announcements/<slug:slug>/', announcement_detail, name='announcement-detail'),
    path('announcements/<slug:slug>/edit/', announcement_update, name='announcement-update'),
    path('announcements/<slug:slug>/delete/', announcement_delete, name='announcement-delete'),

 # Customer-facing transaction routes
    path('my-orders/', customer_orders_list, name='customer-orders'),
    path('my-orders/<int:order_id>/cancel/', cancel_customer_order, name='customer-cancel-order'),
    path('my-orders/<int:order_id>/delete/', delete_customer_order, name='customer-delete-order'),
    path('my-bookings/', customer_bookings_list, name='customer-bookings'),
    path('my-bookings/<int:booking_id>/cancel/', cancel_customer_booking, name='customer-cancel-booking'),
    path('my-bookings/<int:booking_id>/delete/', delete_customer_booking, name='customer-delete-booking'),

    #Cart
    path("cart/", cart_detail, name="cart_detail"),
    path("cart/add/<int:product_id>/", add_to_cart, name="add_to_cart"),
    path("cart/item/<int:item_id>/update/", update_cart_item, name="update_cart_item"),
    path("cart/item/<int:item_id>/remove/", remove_cart_item, name="remove_cart_item"),
    path("checkout/", checkout, name="checkout"),

    # Business Owner transaction management routes
    path('vendor/orders/', owner_orders_list, name='owner-orders'),
    path('vendor/bookings/', owner_bookings_list, name='owner-bookings'),
    path('vendor/order/<int:order_id>/update/', update_order_status, name='update-order-status'),
    path('vendor/booking/<int:booking_id>/update/', update_booking_status, name='update-booking-status'),

]