from django.urls import path
from .views import (
    add_to_cart,
    cancel_customer_booking,
    cancel_customer_order,
    cart_detail,
    checkout,
    create_booking,
    customer_bookings_list,
    customer_orders_list,
    delete_customer_booking,
    delete_customer_order,
    owner_bookings_list,
    owner_orders_list,
    remove_cart_item,
    update_booking_status,
    update_cart_item,
    update_order_status,
)

app_name = "transactions"
urlpatterns = [
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

    #Service Booking
    path('store/<slug:store_slug>/<slug:service_slug>/booking/new/', create_booking, name='create-booking'),

    # Business Owner transaction management routes
    path('vendor/orders/', owner_orders_list, name='owner-orders'),
    path('vendor/bookings/', owner_bookings_list, name='owner-bookings'),
    path('vendor/order/<int:order_id>/update/', update_order_status, name='update-order-status'),
    path('vendor/booking/<int:booking_id>/update/', update_booking_status, name='update-booking-status'),
]