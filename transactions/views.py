from collections import defaultdict
from decimal import Decimal
import json
import logging
import re
from urllib.parse import quote
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import F
from django.db.models.deletion import ProtectedError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import strip_tags
from django.views.decorators.http import require_POST

from accounts.models import User
from core.whatsapp import send_whatsapp_async
from stores.models import Product, Service, Store
from .models import (
    AvailabilitySlot,
    Booking,
    Cart,
    CartItem,
    Order,
    OrderItem,
    OrderStatusHistory,
    VendorNotification,
)

logger = logging.getLogger(__name__)


# ==========================================
# 1. CUSTOMER VIEWS (Placing & Viewing History)
# ==========================================
@login_required
def cart_detail(request):
    cart, _ = Cart.objects.get_or_create(customer=request.user)
    items = list(
        cart.items.select_related("product", "product__store").all()  # type: ignore
    )

    # Group items by store so the customer sees how their cart splits per vendor
    grouped_by_store = defaultdict(lambda: {"items": [], "subtotal": Decimal("0.00")})
    for item in items:
        store = item.product.store
        grouped_by_store[store]["items"].append(item)
        grouped_by_store[store]["subtotal"] += item.line_total

    context = {
        "cart": cart,
        "items": items,
        "grouped_stores": dict(grouped_by_store),
    }
    return render(request, "transactions/cart_detail.html", context)


@login_required
def checkout(request):
    cart = get_object_or_404(Cart, customer=request.user)
    cart_items = list(
        cart.items.select_related("product", "product__store", "product__store__owner")  # type: ignore
    )
    store = CartItem.objects.filter(cart=cart).first().product.store if cart_items else None  # type: ignore

    if not cart_items:
        messages.warning(request, "Your cart is empty.")
        return redirect("transactions:cart_detail")

    # Pre-fill contact & campus residence details from CustomerProfile if available
    profile = getattr(request.user, "customer_profile", None)
    default_phone = getattr(profile, "phone", "") or getattr(request.user, "phone", "")
    residence = (
        User.objects.filter(id=request.user.id).first().residence # type: ignore
        if hasattr(request.user, "residence")
        else ""
    )  # type: ignore
    room_number = (
        User.objects.filter(id=request.user.id).first().room_number # type: ignore
        if hasattr(request.user, "room_number")
        else ""
    )  # type: ignore

    delivery_location = f"{residence} {room_number}".strip()
    pickup_location = (
        Store.objects.filter(name=store.name).first().pickup_location if store else "" # type: ignore
    )  # type: ignore

    # Group items by store for display and per-store order creation
    items_by_store = defaultdict(list)
    for item in cart_items:
        items_by_store[item.product.store].append(item)

    if request.method == "POST":
        customer_name = (
            request.POST.get("customer_name", "").strip()
            or request.user.get_full_name()
            or request.user.email
        )
        customer_phone = request.POST.get("customer_phone", "").strip()
        fulfilment_method = request.POST.get(
            "fulfilment_method", Order.Fulfilment.PICKUP
        )
        pickup_location = request.POST.get("pickup_location", "").strip()
        delivery_address = request.POST.get("delivery_address", "").strip()
        payment_method = request.POST.get(
            "payment_method", Order.PaymentMethod.CASH
        )
        customer_note = request.POST.get("customer_note", "").strip()

        # Validate choice values against your TextChoices
        if fulfilment_method not in Order.Fulfilment.values:
            fulfilment_method = Order.Fulfilment.PICKUP
        if payment_method not in Order.PaymentMethod.values:
            payment_method = Order.PaymentMethod.CASH

        if not customer_phone:
            messages.error(
                request,
                "Please provide a phone or WhatsApp number so the store can contact you.",
            )
            return redirect("transactions:checkout")

        if fulfilment_method == Order.Fulfilment.DELIVERY and not delivery_address:
            messages.error(
                request, "Please enter a delivery address or campus hall/room."
            )
            return redirect("transactions:checkout")

        shared_checkout_ref = uuid.uuid4()
        created_orders = []

        try:
            with transaction.atomic():
                # Lock all involved products to prevent overselling
                product_ids = [item.product_id for item in cart_items]
                locked_products = {
                    p.pk: p
                    for p in Product.objects.select_for_update().filter(pk__in=product_ids)
                }

                # Verify stock before creating any orders
                for item in cart_items:
                    product = locked_products[item.product_id]
                    if hasattr(product, "stock") and product.stock is not None:
                        if product.stock < item.quantity:
                            raise ValidationError(
                                f"Sorry, only {product.stock} unit(s) of '{product.name}' remain in stock."
                            )

                # Create one Order per store sharing the same checkout_reference
                for store, store_items in items_by_store.items():
                    order = Order.objects.create(
                        checkout_reference=shared_checkout_ref,
                        customer=request.user,
                        store=store,
                        customer_name=customer_name,
                        customer_phone=customer_phone,
                        customer_email=request.user.email,
                        fulfilment_method=fulfilment_method,
                        pickup_location=pickup_location,
                        delivery_address=delivery_address,
                        payment_method=payment_method,
                        customer_note=customer_note,
                    )

                    OrderItem.objects.bulk_create(
                        [
                            OrderItem(
                                order=order,
                                product=item.product,
                                product_name=item.product.name,
                                variant_name=item.variant_name,
                                sku=getattr(item.product, "sku", ""),
                                unit_price=item.product.price,
                                quantity=item.quantity,
                            )
                            for item in store_items
                        ]
                    )

                    # Deduct stock so RELEASES_STOCK on cancel/reject stays balanced
                    for item in store_items:
                        if hasattr(locked_products[item.product_id], "stock"):
                            Product.objects.filter(pk=item.product_id).update(
                                stock=F("stock") - item.quantity
                            )

                    # Calculate and freeze subtotal & total using your model method
                    order.recalculate_totals()
                    order.save(update_fields=["subtotal", "total"])

                    # Log initial status in OrderStatusHistory
                    OrderStatusHistory.objects.create(
                        order=order,
                        from_status="",
                        to_status=Order.Status.PENDING,
                        changed_by=request.user,
                        note="Order placed by customer.",
                    )

                    # Create portal message for the store's dashboard
                    items_lines = "\n".join(
                        f"- {i.quantity} × {i.product.name}"
                        f"{f' ({i.variant_name})' if i.variant_name else ''}"
                        f" — MUR {i.line_total}"
                        for i in store_items
                    )
                    location_info = (
                        f"Delivery to: {delivery_address}"
                        if fulfilment_method == Order.Fulfilment.DELIVERY
                        else f"Pickup at: {pickup_location or 'Campus / Store default'}"
                    )
                    portal_message = (
                        f"New Order {order.order_number} from {customer_name}\n"
                        f"Phone/WhatsApp: {customer_phone}\n"
                        f"Email: {request.user.email}\n"
                        f"Fulfilment: {order.get_fulfilment_method_display()} ({location_info})\n"
                        f"Payment: {order.get_payment_method_display()}\n"
                        f"Customer Note: {customer_note or 'None'}\n\n"
                        f"Items:\n{items_lines}\n\n"
                        f"Order Total: MUR {order.total}\n"
                        f"Please contact the customer to confirm and coordinate."
                    )

                    VendorNotification.objects.create(
                        store=store,
                        order=order,
                        title=f"New Order {order.order_number} (MUR {order.total})",
                        message=portal_message,
                    )

                    created_orders.append((store, order, portal_message))

                # Clear the cart once all orders succeed
                cart.items.all().delete()  # type: ignore

        except ValidationError as exc:
            messages.error(request, exc.message)
            return redirect("transactions:cart_detail")

        # Send notifications AFTER transaction commits so network issues never roll back orders
        _send_order_notifications(
            request.user, customer_name, created_orders, request=request
        )

        return render(
            request,
            "transactions/checkout_success.html",
            {
                "orders": [order for _, order, _ in created_orders],
                "checkout_reference": shared_checkout_ref,
            },
        )

    context = {
        "cart": cart,
        "items": cart_items,
        "items_by_store": dict(items_by_store),
        "default_name": request.user.get_full_name() or "",
        "default_phone": default_phone,
        "delivery_location": delivery_location,
        "pickup_location": pickup_location,
        "fulfilment_choices": Order.Fulfilment.choices,
        "payment_choices": Order.PaymentMethod.choices,
    }
    return render(request, "transactions/checkout.html", context)


def _abs_url(base_url: str, path: str) -> str:
    if not path:
        return ""
    if path.startswith(("http://", "https://")):
        return path
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _digits_only(phone: str) -> str:
    digits = re.sub(r"\D", "", str(phone or ""))
    if len(digits) == 8 and digits.startswith("5"):
        return f"230{digits}"
    return digits


def _build_order_notification_payload(
    store, order, base_url: str, support_email: str, support_phone: str
) -> dict:
    """Prepares action links, contact details, and itemized data for WhatsApp and email fallback."""
    store_logo_url = (
        _abs_url(base_url, store.logo.url) if getattr(store, "logo", None) else ""
    )
    store_url = _abs_url(
        base_url, reverse("store:store-profile", kwargs={"slug": store.slug})
    )
    review_url = _abs_url(
        base_url, reverse("store:submit-review", kwargs={"slug": store.slug})
    )
    track_url = f"{_abs_url(base_url, reverse('transactions:customer-orders'))}?ref={order.checkout_reference}"

    vendor_email = getattr(store, "contact_email", "") or getattr(store.owner, "email", "")
    vendor_phone = getattr(store, "contact_phone", "") or getattr(store.owner, "phone", "")
    vendor_digits = _digits_only(vendor_phone)

    contact_text = quote(
        f"Hi {store.name}, I have a question about Order {order.order_number} on The Spotlight."
    )
    contact_store_url = (
        f"https://wa.me/{vendor_digits}?text={contact_text}"
        if vendor_digits
        else (f"mailto:{vendor_email}?subject={contact_text}" if vendor_email else store_url)
    )

    support_digits = _digits_only(support_phone)
    report_text = quote(
        f"[Issue Report] Order {order.order_number} (Ref: {order.checkout_reference})"
    )
    report_url = (
        f"https://wa.me/{support_digits}?text={report_text}"
        if support_digits
        else f"mailto:{support_email}?subject={report_text}"
    )

    items_data = []
    for item in order.items.select_related("product").all():
        image_url = (
            _abs_url(base_url, item.product.image.url)
            if item.product and getattr(item.product, "image", None)
            else ""
        )
        items_data.append(
            {
                "name": item.display_name,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "line_total": item.line_total,
                "image_url": image_url,
            }
        )

    return {
        "store": store,
        "order": order,
        "store_logo_url": store_logo_url,
        "vendor_email": vendor_email,
        "vendor_phone": vendor_phone,
        "store_location": getattr(store, "pickup_location", "")
        or getattr(store, "location", ""),
        "store_url": store_url,
        "review_url": review_url,
        "track_url": track_url,
        "contact_store_url": contact_store_url,
        "report_url": report_url,
        "items": items_data,
    }


def _send_order_notifications(customer, customer_name, created_orders, request=None):
    sender = getattr(
        settings, "DEFAULT_FROM_EMAIL", "The Spotlight <e.mugisha7@gmail.com>"
    )
    support_email = getattr(settings, "SUPPORT_EMAIL", "e.mugisha7@gmail.com")
    support_phone = getattr(settings, "SUPPORT_WHATSAPP_PHONE", "")
    base_url = (
        request.build_absolute_uri("/").rstrip("/")
        if request is not None
        else getattr(settings, "SITE_URL", "http://127.0.0.1:8000").rstrip("/")
    )

    enriched_orders = [
        _build_order_notification_payload(
            store, order, base_url, support_email, support_phone
        )
        for store, order, _ in created_orders
    ]

    # 1. Notify each seller/store via WhatsApp (fallback to email if no phone is set)
    for payload in enriched_orders:
        vendor_phone = payload["vendor_phone"]
        vendor_email = payload["vendor_email"]
        order = payload["order"]
        store = payload["store"]
        buyer_phone = order.customer_phone or getattr(customer, "phone", "")

        if vendor_phone:
            item_lines = "\n".join(
                f"• {i['quantity']}x {i['name']} — MUR {i['line_total']}"
                for i in payload["items"]
            )
            fulfilment_line = (
                f"Delivery to: {order.delivery_address}"
                if order.fulfilment_method == Order.Fulfilment.DELIVERY
                else f"Pickup at: {order.pickup_location or 'Store default'}"
            )
            buyer_digits = _digits_only(buyer_phone)
            chat_buyer = (
                f"\nChat with buyer: https://wa.me/{buyer_digits}" if buyer_digits else ""
            )

            vendor_msg = (
                f"*[The Spotlight] New Order {order.order_number}*\n"
                f"Store: *{store.name}*\n\n"
                f"*Items:*\n{item_lines}\n\n"
                f"*Total:* MUR {order.total}\n"
                f"*Fulfilment:* {order.get_fulfilment_method_display()} ({fulfilment_line})\n"
                f"*Payment:* {order.get_payment_method_display()}\n"
                f"*Buyer:* {customer_name} ({buyer_phone})"
                f"{chat_buyer}"
            )
            transaction.on_commit(
                lambda phone=vendor_phone, msg=vendor_msg: send_whatsapp_async(phone, msg)
            )
        elif vendor_email:
            html_body = render_to_string(
                "emails/vendor_new_order.html",
                {
                    **payload,
                    "buyer_name": customer_name,
                    "buyer_email": order.customer_email or customer.email,
                    "buyer_phone": buyer_phone,
                    "support_email": support_email,
                },
            )
            msg = EmailMultiAlternatives(
                subject=f"[The Spotlight] New Order {order.order_number} — {store.name}",
                body=strip_tags(html_body),
                from_email=sender,
                to=[vendor_email],
                reply_to=[order.customer_email] if order.customer_email else None,
            )
            msg.attach_alternative(html_body, "text/html")
            msg.send(fail_silently=True)

    # 2. Send consolidated confirmation to the customer via WhatsApp (fallback to email)
    if enriched_orders:
        first_order = enriched_orders[0]["order"]
        customer_phone = first_order.customer_phone or getattr(customer, "phone", "")
        checkout_ref = first_order.checkout_reference
        grand_total = sum(p["order"].total for p in enriched_orders)
        global_track_url = f"{_abs_url(base_url, reverse('transactions:customer-orders'))}?ref={checkout_ref}"

        if customer_phone:
            sections = []
            for p in enriched_orders:
                store = p["store"]
                order = p["order"]
                item_lines = "\n".join(
                    f"  • {i['quantity']}x {i['name']} (MUR {i['line_total']})"
                    for i in p["items"]
                )
                sections.append(
                    f"*{store.name}* (Order {order.order_number})\n"
                    f"{item_lines}\n"
                    f"  Subtotal: *MUR {order.total}*\n"
                    f"  Contact store: {p['contact_store_url']}\n"
                    f"  Review: {p['review_url']}"
                )

            customer_msg = (
                f"*[The Spotlight] Order Confirmed!* 🎉\n"
                f"Hi {customer_name or 'there'}, your order has been placed.\n"
                f"*Checkout Ref:* #{str(checkout_ref)[:8].upper()}\n\n"
                + "\n\n".join(sections)
                + f"\n\n*Grand Total:* MUR {grand_total}\n"
                f"View orders: {global_track_url}"
            )
            transaction.on_commit(
                lambda phone=customer_phone, msg=customer_msg: send_whatsapp_async(
                    phone, msg
                )
            )
        elif customer.email:
            html_body = render_to_string(
                "emails/customer_order_confirmation.html",
                {
                    "customer_name": customer_name,
                    "customer_email": customer.email,
                    "checkout_reference": checkout_ref,
                    "grand_total": grand_total,
                    "orders_data": enriched_orders,
                    "global_track_url": global_track_url,
                    "global_report_url": enriched_orders[0]["report_url"],
                    "support_email": support_email,
                },
            )
            msg = EmailMultiAlternatives(
                subject=f"[The Spotlight] Order Confirmation — Ref #{str(checkout_ref)[:8].upper()}",
                body=strip_tags(html_body),
                from_email=sender,
                to=[customer.email],
            )
            msg.attach_alternative(html_body, "text/html")
            msg.send(fail_silently=True)


@login_required
def add_to_cart(request, product_id):
    product = get_object_or_404(Product, pk=product_id, is_available=True)

    # 1. If a logged-out user clicked "Add to Cart" and just finished logging in,
    # Django redirects them here via GET (?next=...). Send them back to the product page.
    if request.method != "POST":
        return redirect(request.META.get("HTTP_REFERER"))

    # 2. Prevent store owners from adding their own products
    if getattr(product.store, "owner_id", None) == request.user.id:
        msg = "You cannot add your own store's product to your cart."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"status": "error", "message": msg}, status=400)
        messages.warning(request, msg)
        return redirect(request.META.get("HTTP_REFERER", "marketplace:home"))

    # 3. Parse quantity, variant_name, and optional JSON customizations
    try:
        quantity = max(1, int(request.POST.get("quantity", 1)))
    except (ValueError, TypeError):
        quantity = 1

    variant_name = request.POST.get("variant_name", "").strip()

    raw_options = request.POST.get("selected_options", "")
    try:
        selected_options = json.loads(raw_options) if raw_options else {}
        if not isinstance(selected_options, dict):
            selected_options = {}
    except json.JSONDecodeError:
        selected_options = {}

    # 4. Add or increment inside an atomic transaction with stock checks
    with transaction.atomic():
        cart, _ = Cart.objects.get_or_create(customer=request.user)

        cart_item, created = CartItem.objects.select_for_update().get_or_create(
            cart=cart,
            product=product,
            variant_name=variant_name,
            defaults={
                "quantity": quantity,
                "selected_options": selected_options,
            },
        )

        new_quantity = quantity if created else cart_item.quantity + quantity

        # Enforce stock limit (if Product has a stock field)
        if hasattr(product, "stock") and product.stock is not None:
            if product.stock <= 0:
                if created:
                    cart_item.delete()
                msg = f"{product.name} is currently out of stock."
                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return JsonResponse({"status": "error", "message": msg}, status=400)
                messages.error(request, msg)
                return redirect(request.META.get("HTTP_REFERER", "marketplace:home"))

            if new_quantity > product.stock:
                new_quantity = product.stock
                messages.warning(
                    request,
                    f"Only {product.stock} unit(s) of {product.name} available; cart updated to max stock.",
                )

        if not created:
            cart_item.quantity = new_quantity
            if selected_options:
                cart_item.selected_options = selected_options
            cart_item.save(update_fields=["quantity", "selected_options"])
        elif new_quantity != quantity:
            cart_item.quantity = new_quantity
            cart_item.save(update_fields=["quantity"])

    success_msg = f"Added {quantity} × {product.name} to your cart."

    # 5. Support both AJAX (fetch) and standard form POST
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse(
            {
                "status": "ok",
                "message": success_msg,
                "cart_total_items": cart.total_items,
                "cart_subtotal": str(cart.subtotal),
            }
        )

    messages.success(request, success_msg)
    return redirect(request.META.get("HTTP_REFERER", "marketplace:home"))


@login_required
@require_POST
def update_cart_item(request, item_id):
    cart_item = get_object_or_404(CartItem, pk=item_id, cart__customer=request.user)
    try:
        quantity = int(request.POST.get("quantity", 1))
    except (ValueError, TypeError):
        quantity = 1

    if quantity <= 0:
        cart_item.delete()
        messages.info(request, "Item removed from your cart.")
    else:
        if hasattr(cart_item.product, "stock") and cart_item.product.stock is not None:
            quantity = min(quantity, cart_item.product.stock)
        cart_item.quantity = quantity
        cart_item.save(update_fields=["quantity"])
        messages.success(request, "Cart updated.")

    return redirect("transactions:cart_detail")


@login_required
@require_POST
def remove_cart_item(request, item_id):
    cart_item = get_object_or_404(CartItem, pk=item_id, cart__customer=request.user)
    cart_item.delete()
    messages.info(request, "Item removed from your cart.")
    return redirect("transactions:cart_detail")


@login_required
def customer_orders_list(request):
    my_orders = list(
        Order.objects.filter(customer=request.user)
        .select_related("store", "store__owner")
        .prefetch_related("items__product")
        .order_by("-created_at")
    )
    support_email = getattr(settings, "SUPPORT_EMAIL", "e.mugisha7@gmail.com")
    for order in my_orders:
        vendor_email = order.store.contact_email or order.store.owner.email
        edit_subject = quote(f"Edit request for order {order.order_number}")
        edit_body = quote(
            f"Hello {order.store.name},\n\n"
            f"I would like to request a change to order {order.order_number}."
        )
        report_subject = quote(f"[Issue Report] Order {order.order_number}")
        order.edit_request_url = (
            f"mailto:{vendor_email}?subject={edit_subject}&body={edit_body}"
            if vendor_email
            else ""
        )  # type: ignore[attr-defined]
        order.report_url = f"mailto:{support_email}?subject={report_subject}"  # type: ignore[attr-defined]

    return render(
        request,
        "transactions/customer_orders.html",
        {"orders": my_orders},
    )


@login_required
@require_POST
def cancel_customer_order(request, order_id):
    order = get_object_or_404(
        Order.objects.select_related("store"),
        pk=order_id,
        customer=request.user,
    )
    if not order.can_customer_cancel:
        messages.error(request, "Only pending orders can be cancelled.")
    else:
        try:
            order.change_status(
                Order.Status.CANCELLED,
                by=request.user,
                note="Cancelled by customer",
            )
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "Your order has been cancelled.")
    return redirect("transactions:customer-orders")


@login_required
@require_POST
def delete_customer_order(request, order_id):
    order = get_object_or_404(
        Order,
        pk=order_id,
        customer=request.user,
    )
    if order.status != Order.Status.CANCELLED:
        messages.error(request, "Only cancelled orders can be deleted.")
        return redirect("transactions:customer-orders")

    try:
        order.delete()
    except ProtectedError:
        messages.error(
            request,
            "This order cannot be deleted because it is linked to a review.",
        )
    else:
        messages.success(request, "The cancelled order has been deleted.")
    return redirect("transactions:customer-orders")


@login_required
def customer_bookings_list(request):
    tracking_reference = request.GET.get("ref", "").strip()
    bookings = Booking.objects.filter(customer=request.user)
    if tracking_reference:
        bookings = bookings.filter(reference=tracking_reference)

    my_bookings = list(
        bookings.select_related(
            "service", "service__store", "service__store__owner", "slot"
        ).order_by("-created_at")
    )
    support_email = getattr(settings, "SUPPORT_EMAIL", "e.mugisha7@gmail.com")
    for booking in my_bookings:
        vendor_email = (
            booking.service.store.contact_email or booking.service.store.owner.email
        )
        edit_subject = quote(f"Edit request for booking {booking.reference}")
        edit_body = quote(
            f"Hello {booking.service.store.name},\n\n"
            f"I would like to request a change to booking {booking.reference} "
            f"for {booking.service.name}."
        )
        report_subject = quote(f"[Issue Report] Booking {booking.reference}")
        booking.edit_request_url = (  # type: ignore
            f"mailto:{vendor_email}?subject={edit_subject}&body={edit_body}"
            if vendor_email
            else ""
        )
        booking.report_url = f"mailto:{support_email}?subject={report_subject}"  # type: ignore

    return render(
        request,
        "transactions/customer_bookings.html",
        {"bookings": my_bookings, "tracking_reference": tracking_reference},
    )


@login_required
@require_POST
def cancel_customer_booking(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related("service", "slot"),
        pk=booking_id,
        customer=request.user,
    )
    try:
        booking.cancel_by_customer()
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "Your booking has been cancelled.")
    return redirect("transactions:customer-bookings")


@login_required
@require_POST
def delete_customer_booking(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id, customer=request.user)
    if booking.status not in (
        Booking.Status.CANCELLED_BY_CUSTOMER,
        Booking.Status.CANCELLED_BY_VENDOR,
    ):
        messages.error(request, "Only cancelled bookings can be deleted.")
        return redirect("transactions:customer-bookings")

    try:
        booking.delete()
    except ProtectedError:
        messages.error(
            request,
            "This booking cannot be deleted because it is linked to a review.",
        )
    else:
        messages.success(request, "The cancelled booking has been deleted.")
    return redirect("transactions:customer-bookings")


@login_required
def create_booking(request, store_slug, service_slug):
    store = Store.objects.filter(
        slug=store_slug,
        status=Store.Status.ACTIVE,
    ).first()
    if not store or not store.accepts_bookings:
        return redirect("stores-home")

    service = Service.objects.filter(
        slug=service_slug,
        store=store,
        is_available=True,
    ).first()
    if not service:
        return redirect("stores-home")

    slots = (
        AvailabilitySlot.objects.all()
        .filter(
            service=service,
            is_active=True,
        )
        .order_by("start_at")
    )
    default_phone = getattr(request.user, "phone", "")
    form_data = {
        "customer_phone": default_phone,
        "seats": 1,
        "customer_note": "",
        "slot_id": "",
    }
    form_error = ""

    if request.method == "POST":
        form_data.update(
            {
                "customer_phone": request.POST.get("customer_phone", "").strip(),
                "seats": request.POST.get("seats", "1").strip(),
                "customer_note": request.POST.get("customer_note", "").strip(),
                "slot_id": request.POST.get("slot_id", "").strip(),
            }
        )

        try:
            seats = int(form_data["seats"])
        except (ValueError, TypeError):
            seats = 0

        if not form_data["customer_phone"]:
            form_error = "Enter a phone number so the provider can contact you."
        elif seats < 1:
            form_error = "Choose at least one seat."
        elif not form_data["slot_id"].isdigit():
            form_error = "Choose an available appointment time."
        else:
            slot = slots.filter(pk=form_data["slot_id"]).first()
            if not slot:
                form_error = "That time is no longer available. Please choose another."
            else:
                try:
                    with transaction.atomic():
                        booking = slot.book(
                            customer=request.user,
                            seats=seats,
                            note=form_data["customer_note"],
                            phone=form_data["customer_phone"],
                        )
                        VendorNotification.objects.create(
                            store=store,
                            title=f"New booking {booking.reference}",
                            message=(
                                f"New booking request from {request.user.get_full_name() or request.user.email}\n"
                                f"Service: {service.name}\n"
                                f"Date and time: {booking.start_at:%a, %d %b %Y, %H:%M}\n"
                                f"People: {booking.seats}\n"
                                f"Phone/WhatsApp: {booking.customer_phone}\n"
                                f"Customer email: {request.user.email}\n"
                                f"Customer note: {booking.customer_note or 'None'}\n"
                                f"Estimated total: MUR {booking.total_price}"
                            ),
                        )
                except ValidationError as error:
                    form_error = " ".join(error.messages)
                else:
                    _send_booking_notifications(request, booking)
                    messages.success(request, "Your booking request has been submitted.")
                    return render(
                        request,
                        "transactions/booking_success.html",
                        {"booking": booking},
                    )

    context = {
        "store": store,
        "service": service,
        "slots": slots,
        "default_name": request.user.get_full_name() or request.user.email,
        "default_email": request.user.email,
        "form_data": form_data,
        "form_error": form_error,
    }
    return render(request, "transactions/create_booking.html", context)


def _send_booking_notifications(request, booking):
    store = booking.service.store
    vendor_phone = getattr(store, "contact_phone", "") or getattr(store.owner, "phone", "")
    vendor_email = store.contact_email or store.owner.email
    customer_phone = booking.customer_phone or getattr(booking.customer, "phone", "")
    base_url = request.build_absolute_uri("/").rstrip("/")
    track_url = (
        f"{_abs_url(base_url, reverse('transactions:customer-bookings'))}?ref={booking.reference}"
    )

    # 1. Customer WhatsApp notification (fallback to email)
    if customer_phone:
        vendor_digits = _digits_only(vendor_phone)
        contact_line = (
            f"\nContact provider: https://wa.me/{vendor_digits}" if vendor_digits else ""
        )
        customer_msg = (
            f"*[The Spotlight] Booking Request Received*\n"
            f"Ref: *{booking.reference}*\n"
            f"Service: *{booking.service.name}* ({store.name})\n"
            f"When: {booking.start_at:%a, %d %b %Y at %H:%M}\n"
            f"Seats: {booking.seats}\n"
            f"Estimated Total: MUR {booking.total_price}"
            f"{contact_line}\n"
            f"Manage booking: {track_url}"
        )
        transaction.on_commit(
            lambda phone=customer_phone, msg=customer_msg: send_whatsapp_async(phone, msg)
        )
    elif booking.customer.email:
        sender = getattr(
            settings, "DEFAULT_FROM_EMAIL", "The Spotlight <noreply@example.com>"
        )
        html_body = render_to_string(
            "emails/customer_booking_confirmation.html",
            {
                "booking": booking,
                "customer": booking.customer,
                "service": booking.service,
                "store": store,
                "store_logo_url": _abs_url(base_url, store.logo.url) if store.logo else "",
                "service_image_url": (
                    _abs_url(base_url, booking.service.image.url)
                    if booking.service.image
                    else ""
                ),
                "store_url": _abs_url(
                    base_url,
                    reverse("store:store-profile", kwargs={"slug": store.slug}),
                ),
                "global_track_url": track_url,
            },
        )
        message = EmailMultiAlternatives(
            subject=f"[The Spotlight] Booking request received — {booking.reference}",
            body=strip_tags(html_body),
            from_email=sender,
            to=[booking.customer.email],
        )
        message.attach_alternative(html_body, "text/html")
        message.send(fail_silently=True)

    # 2. Vendor WhatsApp notification (fallback to email)
    if vendor_phone:
        customer_digits = _digits_only(customer_phone)
        chat_customer = (
            f"\nChat with customer: https://wa.me/{customer_digits}"
            if customer_digits
            else ""
        )
        vendor_msg = (
            f"*[The Spotlight] New Booking Request — {booking.reference}*\n"
            f"Service: *{booking.service.name}*\n"
            f"Customer: {booking.customer.get_full_name() or booking.customer.email}\n"
            f"Phone: {customer_phone}\n"
            f"When: {booking.start_at:%a, %d %b %Y at %H:%M}\n"
            f"Seats: {booking.seats}\n"
            f"Estimated Total: MUR {booking.total_price}\n"
            f"Note: {booking.customer_note or 'None'}"
            f"{chat_customer}"
        )
        transaction.on_commit(
            lambda phone=vendor_phone, msg=vendor_msg: send_whatsapp_async(phone, msg)
        )
    elif vendor_email:
        sender = getattr(
            settings, "DEFAULT_FROM_EMAIL", "The Spotlight <noreply@example.com>"
        )
        html_body = render_to_string(
            "emails/vendor_new_booking.html",
            {
                "booking": booking,
                "customer": booking.customer,
                "service": booking.service,
                "store": store,
                "store_logo_url": _abs_url(base_url, store.logo.url) if store.logo else "",
                "service_image_url": (
                    _abs_url(base_url, booking.service.image.url)
                    if booking.service.image
                    else ""
                ),
                "store_url": _abs_url(
                    base_url,
                    reverse("store:store-profile", kwargs={"slug": store.slug}),
                ),
                "global_track_url": track_url,
            },
        )
        message = EmailMultiAlternatives(
            subject=f"[The Spotlight] New booking request — {booking.reference}",
            body=strip_tags(html_body),
            from_email=sender,
            to=[vendor_email],
        )
        message.attach_alternative(html_body, "text/html")
        message.send(fail_silently=True)


# ==========================================
# 2. BUSINESS OWNER VIEWS (Fulfillment & Management)
# ==========================================
@login_required
def owner_orders_list(request):
    store = Store.objects.filter(vendor__user=request.user).first()
    if not store:
        return redirect("store-dashboard")

    orders = Order.objects.filter(store=store).order_by("-created_at")
    context = {"store": store, "orders": orders}
    return render(request, "transactions/owner_orders.html", context)


@login_required
def owner_bookings_list(request):
    store = Store.objects.filter(vendor__user=request.user).first()
    if not store:
        return redirect("store-dashboard")

    bookings = Booking.objects.filter(store=store).order_by("-booking_date")
    context = {"store": store, "bookings": bookings}
    return render(request, "transactions/owner_bookings.html", context)


@login_required
def update_order_status(request, order_id):
    order = Order.objects.filter(id=order_id, store__vendor__user=request.user).first()
    if not order:
        return redirect("store-dashboard")

    if request.method == "POST":
        new_status = request.POST.get("status")
        if new_status:
            order.status = new_status
            order.save(update_fields=["status"])

    return redirect("owner-orders")


@login_required
def update_booking_status(request, booking_id):
    booking = Booking.objects.filter(
        id=booking_id, store__vendor__user=request.user
    ).first()
    if not booking:
        return redirect("store-dashboard")

    if request.method == "POST":
        new_status = request.POST.get("status")
        if new_status:
            booking.status = new_status
            booking.save(update_fields=["status"])

    return redirect("owner-bookings")