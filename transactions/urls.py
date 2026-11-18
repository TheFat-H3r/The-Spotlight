from django.urls import path
from .views import create_booking, create_order, customer_bookings_list, customer_orders_list, owner_bookings_list, owner_orders_list, update_booking_status, update_order_status

urlpatterns = [
    # Customer-facing transaction routes
    path('my-orders/', customer_orders_list, name='customer-orders'),
    path('my-bookings/', customer_bookings_list, name='customer-bookings'),
    path('store/<slug:store_slug>/order/new/', create_order, name='create-order'),
    path('store/<slug:store_slug>/booking/new/', create_booking, name='create-booking'),

    # Business Owner transaction management routes
    path('vendor/orders/', owner_orders_list, name='owner-orders'),
    path('vendor/bookings/', owner_bookings_list, name='owner-bookings'),
    path('vendor/order/<int:order_id>/update/', update_order_status, name='update-order-status'),
    path('vendor/booking/<int:booking_id>/update/', update_booking_status, name='update-booking-status'),
]