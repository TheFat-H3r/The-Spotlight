from django.conf import settings
from django.db import models
from stores.models import Service, Store


class Booking(models.Model):
  user = models.ForeignKey(
      settings.AUTH_USER_MODEL,
      on_delete=models.CASCADE,
      related_name='bookings',
  )
  store = models.ForeignKey(
      Store, on_delete=models.CASCADE, related_name='bookings'
  )
  service = models.ForeignKey(
      Service,
      on_delete=models.SET_NULL,
      null=True,
      blank=True,
      related_name='bookings',
  )
  booking_date = models.DateTimeField()
  status = models.CharField(max_length=50, default='Pending')
  created_at = models.DateTimeField(auto_now_add=True)

  def __str__(self):
    return f'Booking by {self.user.email} at {self.store.name}'


class Order(models.Model):
  user = models.ForeignKey(
      settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='orders'
  )
  store = models.ForeignKey(
      Store, on_delete=models.CASCADE, related_name='orders'
  )
  total_amount = models.DecimalField(max_digits=10, decimal_places=2)
  status = models.CharField(max_length=50, default='Pending')
  created_at = models.DateTimeField(auto_now_add=True)

  def __str__(self):
    return f'Order #{self.id} by {self.user.email} at {self.store.name}' # type: ignore