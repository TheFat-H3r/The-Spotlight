from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from transactions.models import Booking
from transactions.models import Order, VendorNotification
from stores.models import Review


@receiver(post_save, sender=Order)
def notify_vendor_on_new_order(sender, instance, created, **kwargs):
    if created:
        customer_label = (
            instance.customer_name
            or (instance.customer.get_full_name() if instance.customer else "")
            or "A customer"
        )
        VendorNotification.objects.create(
            store=instance.store,
            order=instance,
            title=f"New Order #{instance.order_number}",
            message=(
                f"{customer_label} placed a {instance.get_fulfilment_method_display().lower()} "
                f"order worth Rs {instance.total:.2f}."
            ),
        )


@receiver(pre_save, sender=Order)
def notify_vendor_on_order_customer_cancel(sender, instance, **kwargs):
    if not instance.pk:
        return
    try:
        previous = Order.objects.get(pk=instance.pk)
    except Order.DoesNotExist:
        return

    if (
        previous.status != Order.Status.CANCELLED
        and instance.status == Order.Status.CANCELLED
    ):
        reason_text = f" Reason: {instance.cancel_reason}" if instance.cancel_reason else ""
        VendorNotification.objects.create(
            store=instance.store,
            order=instance,
            title=f"Order #{instance.order_number} Cancelled",
            message=f"Order #{instance.order_number} was cancelled.{reason_text}",
        )


@receiver(post_save, sender=Booking)
def notify_vendor_on_new_booking(sender, instance, created, **kwargs):
    if created:
        client_name = instance.customer.get_full_name() or instance.customer.email
        slot_time = instance.slot.start_at.strftime("%a %d %b, %H:%M")
        VendorNotification.objects.create(
            store=instance.service.store,
            title=f"New Booking Request ({instance.reference})",
            message=(
                f"{client_name} booked {instance.service.name} "
                f"for {slot_time} ({instance.seats} seat(s))."
            ),
        )


@receiver(pre_save, sender=Booking)
def notify_vendor_on_booking_customer_cancel(sender, instance, **kwargs):
    if not instance.pk:
        return
    try:
        previous = Booking.objects.get(pk=instance.pk)
    except Booking.DoesNotExist:
        return

    if (
        previous.status != Booking.Status.CANCELLED_BY_CUSTOMER
        and instance.status == Booking.Status.CANCELLED_BY_CUSTOMER
    ):
        reason_text = f" Reason: {instance.status_reason}" if instance.status_reason else ""
        VendorNotification.objects.create(
            store=instance.service.store,
            title=f"Booking {instance.reference} Cancelled by Client",
            message=(
                f"Client cancelled their booking for {instance.service.name}.{reason_text}"
            ),
        )


@receiver(post_save, sender=Review)
def notify_vendor_on_new_review(sender, instance, created, **kwargs):
    if created and instance.store_id:
        target = instance.product or instance.service or instance.store
        VendorNotification.objects.create(
            store=instance.store,
            title=f"New {instance.overall_rating}★ Review Received",
            message=f"A customer left a new review on {target}.",
        )