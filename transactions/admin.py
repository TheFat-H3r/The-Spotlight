from django.contrib import admin
from .models import Booking, Order, AvailabilitySlot, OrderStatusHistory, OrderItem, Cart, CartItem

admin.site.register(Booking)
admin.site.register(Order)
admin.site.register(AvailabilitySlot)
admin.site.register(OrderStatusHistory)
admin.site.register(OrderItem)
admin.site.register(Cart)
admin.site.register(CartItem)