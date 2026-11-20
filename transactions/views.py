from collections import defaultdict
from decimal import Decimal
import json
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from urllib.parse import quote
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import strip_tags
from django.db import transaction
from django.db.models import F
from django.forms import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from accounts.models import User
from stores.models import Product, Store
from .models import Booking, Cart, CartItem, Order, OrderItem, OrderStatusHistory, VendorNotification


# ==========================================
# 1. CUSTOMER VIEWS (Placing & Viewing History)
# ==========================================
@login_required
def cart_detail(request):
    cart, _ = Cart.objects.get_or_create(customer=request.user)
    items = list(
        cart.items.select_related("product", "product__store").all() # type: ignore
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
        cart.items.select_related("product", "product__store", "product__store__owner") # type: ignore
    )
    store = CartItem.objects.filter(cart=cart).first().product.store if cart_items else None # type: ignore
    
    if not cart_items:
        messages.warning(request, "Your cart is empty.")
        return redirect("transactions:cart_detail")

    # Pre-fill contact & campus residence details from CustomerProfile if available
    profile = getattr(request.user, "customer_profile", None)
    default_phone = getattr(profile, "phone", "") or getattr(request.user, "phone", "")
    residence = User.objects.filter(id=request.user.id).first().residence if hasattr(request.user, "residence") else "" # type: ignore
    room_number = User.objects.filter(id=request.user.id).first().room_number if hasattr(request.user, "room_number") else "" # type: ignore

    delivery_location = f"{residence} {room_number}".strip()
    pickup_location = Store.objects.filter(name=store.name).first().pickup_location if store else "" # type: ignore
    

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
            messages.error(request, "Please provide a phone or WhatsApp number so the store can contact you.")
            return redirect("transactions:checkout")

        if fulfilment_method == Order.Fulfilment.DELIVERY and not delivery_address:
            messages.error(request, "Please enter a delivery address or campus hall/room.")
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

                    OrderItem.objects.bulk_create([
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
                    ])

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
                cart.items.all().delete() # type: ignore

        except ValidationError as exc:
            messages.error(request, exc.message)
            return redirect("transactions:cart_detail")

        # Send emails AFTER transaction commits so SMTP issues never roll back orders
        _send_order_notifications(request.user, customer_name, created_orders)

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


def _build_order_email_payload(store, order, base_url: str, support_email: str) -> dict:
    """Prepares absolute image URLs, action links, and item data for HTML email templates."""
    store_logo_url = ""
    if getattr(store, "logo", None):
        store_logo_url = _abs_url(base_url, store.logo.url)

    store_url = _abs_url(
        base_url, reverse("store:store-profile", kwargs={"slug": store.slug})
    )
    review_url = _abs_url(
        base_url, reverse("store:submit-review", kwargs={"slug": store.slug})
    )
    # Adjust 'accounts:profile' to your dedicated order-tracking URL if you add one later
    track_url = f"{_abs_url(base_url, reverse('accounts:profile'))}?ref={order.checkout_reference}"

    vendor_email = getattr(store, "email", None) or getattr(store.owner, "email", "")
    vendor_phone = getattr(store, "contact_phone", "")
    contact_subject = quote(f"Question about Order {order.order_number} on The Spotlight")
    contact_store_url = (
        f"mailto:{vendor_email}?subject={contact_subject}"
        if vendor_email
        else store_url
    )

    report_subject = quote(
        f"[Issue Report] Order {order.order_number} (Ref: {order.checkout_reference})"
    )
    report_url = f"mailto:{support_email}?subject={report_subject}"

    items_data = []
    for item in order.items.select_related("product").all():
        image_url = ""
        if item.product and getattr(item.product, "image", None):
            image_url = _abs_url(base_url, item.product.image.url)
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
        "store_location": getattr(store, "location", "") or getattr(store, "address", ""),
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
    base_url = (
        request.build_absolute_uri("/").rstrip("/")
        if request is not None
        else getattr(settings, "SITE_URL", "http://127.0.0.1:8000").rstrip("/")
    )

    enriched_orders = [
        _build_order_email_payload(store, order, base_url, support_email)
        for store, order, _ in created_orders
    ]

    # 1. Notify each seller/store via HTML + Plain Text email (includes full buyer details)
    for payload in enriched_orders:
        vendor_email = payload["vendor_email"]
        order = payload["order"]
        store = payload["store"]

        if vendor_email:
            html_body = render_to_string(
                "emails/vendor_new_order.html",
                {
                    **payload,
                    "buyer_name": customer_name,
                    "buyer_email": order.customer_email or customer.email,
                    "buyer_phone": order.customer_phone,
                    "support_email": support_email,
                },
            )
            text_body = strip_tags(html_body)

            msg = EmailMultiAlternatives(
                subject=f"[The Spotlight] New Order {order.order_number} — {store.name}",
                body=text_body,
                from_email=sender,
                to=[vendor_email],
                reply_to=[order.customer_email] if order.customer_email else None,
            )
            msg.attach_alternative(html_body, "text/html")
            msg.send(fail_silently=True)

    # 2. Send rich confirmation email to the customer
    if customer.email and enriched_orders:
        first_order = enriched_orders[0]["order"]
        checkout_ref = first_order.checkout_reference
        grand_total = sum(p["order"].total for p in enriched_orders)
        global_track_url = (
            f"{_abs_url(base_url, reverse('accounts:profile'))}?ref={checkout_ref}"
        )
        global_report_url = (
            f"mailto:{support_email}?subject="
            f"{quote(f'[Support Request] Checkout Ref {checkout_ref}')}"
        )

        html_body = render_to_string(
            "emails/customer_order_confirmation.html",
            {
                "customer_name": customer_name,
                "customer_email": customer.email,
                "checkout_reference": checkout_ref,
                "grand_total": grand_total,
                "orders_data": enriched_orders,
                "global_track_url": global_track_url,
                "global_report_url": global_report_url,
                "support_email": support_email,
            },
        )
        text_body = strip_tags(html_body)

        msg = EmailMultiAlternatives(
            subject=f"[The Spotlight] Order Confirmation — Ref #{str(checkout_ref)[:8].upper()}",
            body=text_body,
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
  
  my_orders = Order.objects.filter(user=request.user).order_by('-created_at')
  context = {'orders': my_orders}
  return render(request, 'transactions/customer_orders.html', context)


@login_required
def customer_bookings_list(request):
  
  my_bookings = Booking.objects.filter(user=request.user).order_by('-booking_date')
  context = {'bookings': my_bookings}
  return render(request, 'transactions/customer_bookings.html', context)


@login_required
def create_order(request, store_slug):
  
  store = Store.objects.filter(slug=store_slug, status=Store.Status.ACTIVE).first()
  if not store or not store.accepts_orders:
    return redirect('stores-home')

  if request.method == 'POST':
    # Extract order payload / amount from form submission
    total_amount = request.POST.get('total_amount', 0.00)
    
    Order.objects.create(
        user=request.user,
        store=store,
        total_amount=total_amount,
        status='Pending'
    )
    return redirect('customer-orders')

  context = {'store': store}
  return render(request, 'transactions/create_order.html', context)


@login_required
def create_booking(request, store_slug):
  
  store = Store.objects.filter(slug=store_slug, status=Store.Status.ACTIVE).first()
  if not store or not store.accepts_bookings:
    return redirect('stores-home')

  if request.method == 'POST':
    service_id = request.POST.get('service_id')
    booking_date = request.POST.get('booking_date')

    Booking.objects.create(
        user=request.user,
        store=store,
        service_id=service_id,
        booking_date=booking_date,
        status='Pending'
    )
    return redirect('customer-bookings')

  context = {'store': store}
  return render(request, 'transactions/create_booking.html', context)


# ==========================================
# 2. BUSINESS OWNER VIEWS (Fulfillment & Management)
# ==========================================

@login_required
def owner_orders_list(request):
  
  store = Store.objects.filter(vendor__user=request.user).first()
  if not store:
    return redirect('store-dashboard')

  orders = Order.objects.filter(store=store).order_by('-created_at')
  context = {'store': store, 'orders': orders}
  return render(request, 'transactions/owner_orders.html', context)


@login_required
def owner_bookings_list(request):
  
  store = Store.objects.filter(vendor__user=request.user).first()
  if not store:
    return redirect('store-dashboard')

  bookings = Booking.objects.filter(store=store).order_by('-booking_date')
  context = {'store': store, 'bookings': bookings}
  return render(request, 'transactions/owner_bookings.html', context)


@login_required
def update_order_status(request, order_id):
  
  order = Order.objects.filter(id=order_id, store__vendor__user=request.user).first()
  if not order:
    return redirect('store-dashboard')

  if request.method == 'POST':
    new_status = request.POST.get('status')
    if new_status:
      order.status = new_status
      order.save(update_fields=['status'])

  return redirect('owner-orders')


@login_required
def update_booking_status(request, booking_id):
  
  booking = Booking.objects.filter(id=booking_id, store__vendor__user=request.user).first()
  if not booking:
    return redirect('store-dashboard')

  if request.method == 'POST':
    new_status = request.POST.get('status')
    if new_status:
      booking.status = new_status
      booking.save(update_fields=['status'])

  return redirect('owner-bookings')