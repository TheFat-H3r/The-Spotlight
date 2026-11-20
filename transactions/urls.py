from django.urls import path
from .views import add_to_cart, cart_detail, checkout, create_booking, create_order, customer_bookings_list, customer_orders_list, owner_bookings_list, owner_orders_list, remove_cart_item, update_booking_status, update_cart_item, update_order_status

app_name = "transactions"
urlpatterns = [
    # Customer-facing transaction routes
    path('my-orders/', customer_orders_list, name='customer-orders'),
    path('my-bookings/', customer_bookings_list, name='customer-bookings'),

    #Cart
    path("cart/", cart_detail, name="cart_detail"),
    path("cart/add/<int:product_id>/", add_to_cart, name="add_to_cart"),
    path("cart/item/<int:item_id>/update/", update_cart_item, name="update_cart_item"),
    path("cart/item/<int:item_id>/remove/", remove_cart_item, name="remove_cart_item"),
    path("checkout/", checkout, name="checkout"),

    path('store/<slug:store_slug>/order/new/', create_order, name='create-order'),
    path('store/<slug:store_slug>/booking/new/', create_booking, name='create-booking'),

    # Business Owner transaction management routes
    path('vendor/orders/', owner_orders_list, name='owner-orders'),
    path('vendor/bookings/', owner_bookings_list, name='owner-bookings'),
    path('vendor/order/<int:order_id>/update/', update_order_status, name='update-order-status'),
    path('vendor/booking/<int:booking_id>/update/', update_booking_status, name='update-booking-status'),
]