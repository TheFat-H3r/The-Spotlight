from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from stores.models import BusinessType, Service, Store
from .models import AvailabilitySlot, Booking, Order


class CustomerTransactionActionTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            email="customer@example.com", password="password"
        )
        self.other_customer = User.objects.create_user(
            email="other@example.com", password="password"
        )
        owner = User.objects.create_user(
            email="vendor@example.com", password="password", role=User.Role.VENDOR
        )
        business_type = BusinessType.objects.create(
            name="Services", store_type=BusinessType.StoreType.SERVICES
        )
        self.store = Store.objects.create(
            owner=owner, business_type=business_type, name="Test Vendor"
        )
        service = Service.objects.create(
            store=self.store, name="Test Service", slug="test-service"
        )
        slot = AvailabilitySlot.objects.create(
            service=service,
            start_at=timezone.now() + timedelta(days=2),
            end_at=timezone.now() + timedelta(days=2, hours=1),
        )
        self.booking = Booking.objects.create(
            customer=self.customer, service=service, slot=slot
        )
        self.order = Order.objects.create(customer=self.customer, store=self.store)

    def test_customer_can_cancel_own_pending_booking(self):
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse(
                "transactions:customer-cancel-booking",
                args=[self.booking.pk],
            )
        )

        self.assertRedirects(response, reverse("transactions:customer-bookings"))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.CANCELLED_BY_CUSTOMER)

    def test_booking_list_shows_actions_contacts_and_return_link(self):
        self.client.force_login(self.customer)

        response = self.client.get(reverse("transactions:customer-bookings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Request edit")
        self.assertContains(response, "Cancel booking")
        self.assertContains(response, "Report issue")
        self.assertContains(response, "vendor@example.com")
        self.assertContains(response, "Back to Marketplace")

    def test_customer_cannot_delete_active_booking(self):
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse(
                "transactions:customer-delete-booking",
                args=[self.booking.pk],
            )
        )

        self.assertRedirects(response, reverse("transactions:customer-bookings"))
        self.assertTrue(Booking.objects.filter(pk=self.booking.pk).exists())

    def test_customer_can_delete_own_cancelled_booking(self):
        self.booking.status = Booking.Status.CANCELLED_BY_CUSTOMER
        self.booking.save(update_fields=["status"])
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse(
                "transactions:customer-delete-booking",
                args=[self.booking.pk],
            )
        )

        self.assertRedirects(response, reverse("transactions:customer-bookings"))
        self.assertFalse(Booking.objects.filter(pk=self.booking.pk).exists())

    def test_customer_cannot_cancel_another_customers_booking(self):
        self.client.force_login(self.other_customer)

        response = self.client.post(
            reverse(
                "transactions:customer-cancel-booking",
                args=[self.booking.pk],
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_order_list_shows_actions_contacts_and_return_link(self):
        self.client.force_login(self.customer)

        response = self.client.get(reverse("transactions:customer-orders"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Request edit")
        self.assertContains(response, "Cancel order")
        self.assertContains(response, "Report issue")
        self.assertContains(response, "vendor@example.com")
        self.assertContains(response, "Back to Marketplace")

    def test_customer_can_cancel_own_pending_order(self):
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse("transactions:customer-cancel-order", args=[self.order.pk])
        )

        self.assertRedirects(response, reverse("transactions:customer-orders"))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CANCELLED)
        self.assertTrue(self.order.status_history.filter(
            to_status=Order.Status.CANCELLED,
            changed_by=self.customer,
        ).exists())

    def test_customer_cannot_delete_active_order(self):
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse("transactions:customer-delete-order", args=[self.order.pk])
        )

        self.assertRedirects(response, reverse("transactions:customer-orders"))
        self.assertTrue(Order.objects.filter(pk=self.order.pk).exists())

    def test_customer_can_delete_own_cancelled_order(self):
        self.order.change_status(Order.Status.CANCELLED, by=self.customer)
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse("transactions:customer-delete-order", args=[self.order.pk])
        )

        self.assertRedirects(response, reverse("transactions:customer-orders"))
        self.assertFalse(Order.objects.filter(pk=self.order.pk).exists())

    def test_customer_cannot_cancel_another_customers_order(self):
        self.order.customer = self.other_customer
        self.order.save(update_fields=["customer"])
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse("transactions:customer-cancel-order", args=[self.order.pk])
        )

        self.assertEqual(response.status_code, 404)
