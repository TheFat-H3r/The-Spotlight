import csv
from decimal import Decimal
from datetime import datetime, time, timedelta
import json
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models.functions import TruncDate, TruncMonth
from django.forms import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages
from django.db.models import Avg, Count, Q, Sum

from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST

from shopkeeper.context_processors import _resolve_business_mode
from stores.models import Product, Review, Service, Store
from transactions.models import Booking, Order, VendorNotification

ZERO = Decimal("0.00")
def _get_vendor_store(user):
    """Helper to verify vendor access and fetch their store."""
    if getattr(user, "role", None) == "customer" and not user.is_staff:
        return None, redirect("marketplace:home")

    store = Store.objects.filter(owner=user).select_related("business_type").first()
    if not store:
        messages.warning(None, "Please create your store profile first.") # type: ignore
        return None, redirect("shopkeeper:store_profile")

    return store, None

def _pct_change(current_val, previous_val):
    if previous_val > ZERO:
        return round(((current_val - previous_val) / previous_val) * Decimal("100"), 1)
    if current_val > ZERO:
        return Decimal("100.0")
    return Decimal("0.0")

@login_required
def home(request):
    """
    Single-store vendor dashboard adapted dynamically to the store's business type
    (Product business vs. Service business).
    """
    vendor = request.user

    # Prevent pure customer accounts from accessing the vendor dashboard
    if getattr(vendor, "role", None) == "customer" and not vendor.is_staff:
        return redirect("marketplace:home")

    store = (
        Store.objects.filter(owner=vendor)
        .select_related("business_type")
        .first()
    )
    business_mode = _resolve_business_mode(store)
    is_service_business = business_mode in ("service", "both")
    is_product_business = business_mode in ("product", "both")

    today = timezone.localdate()
    now = timezone.now()
    first_day = today - timedelta(days=6)

    # Defaults if the vendor has not created their store yet
    if not store:
        context = {
            "store": None,
            "business_mode": business_mode,
            "is_service_business": is_service_business,
            "is_product_business": is_product_business,
            "today": today,
        }
        return render(request, "shopkeeper/home.html", context)

    # Shared: Reviews & Notifications
    reviews = Review.objects.filter(store=store, status=Review.Status.PUBLISHED)
    review_stats = reviews.aggregate(
        average=Avg("overall_rating"),
        review_count=Count("id"),
    )
    recent_reviews = (
        reviews.select_related("store", "product", "service", "author")
        .order_by("-created_at")[:6]
    )

    notifications = VendorNotification.objects.filter(store=store)
    unread_notifications = notifications.filter(is_read=False).count()
    recent_notifications = notifications.select_related(
        "store", "order"
    ).order_by("-created_at")[:5]

    # Product business data
    product_stats = {"total_count": 0, "available_count": 0}
    order_stats = {
        "total_count": 0,
        "pending": 0,
        "processing": 0,
        "completed": 0,
        "completed_value": ZERO,
        "paid_value": ZERO,
    }
    low_stock_products = []
    recent_orders = []

    if is_product_business:
        products = Product.objects.filter(store=store)
        product_stats = products.aggregate(
            total_count=Count("id"),
            available_count=Count("id", filter=Q(is_available=True)),
        )
        low_stock_products = (
            products.filter(is_available=True, stock__lte=5)
            .select_related("store")
            .order_by("stock", "name")[:6]
        )

        orders = Order.objects.filter(store=store)
        order_stats = orders.aggregate(
            total_count=Count("id"),
            pending=Count("id", filter=Q(status=Order.Status.PENDING)),
            processing=Count(
                "id",
                filter=Q(status__in=[Order.Status.CONFIRMED, Order.Status.PREPARING]),
            ),
            completed=Count("id", filter=Q(status=Order.Status.COMPLETED)),
            completed_value=Sum("total", filter=Q(status=Order.Status.COMPLETED)),
            paid_value=Sum(
                "total",
                filter=Q(
                    status=Order.Status.COMPLETED,
                    payment_status=Order.PaymentStatus.PAID,
                ),
            ),
        )
        recent_orders = (
            orders.select_related("store", "customer")
            .order_by("-created_at")[:100]
        )

    # Service business data
    service_stats = {"total_count": 0, "available_count": 0}
    booking_stats = {
        "total_count": 0,
        "pending": 0,
        "confirmed": 0,
        "completed": 0,
        "completed_value": ZERO,
    }
    recent_bookings = []
    upcoming_slots = []

    if is_service_business:
        services = Service.objects.filter(store=store)
        service_stats = services.aggregate(
            total_count=Count("id"),
            available_count=Count("id", filter=Q(is_available=True)),
        )

        bookings = Booking.objects.filter(service__store=store)
        booking_price_field = (
            "total"
            if hasattr(Booking, "total")
            else ("total_price" if hasattr(Booking, "total_price") else "service__price")
        )
        booking_stats = bookings.aggregate(
            total_count=Count("id"),
            pending=Count("id", filter=Q(status=Booking.Status.PENDING)),
            confirmed=Count("id", filter=Q(status=Booking.Status.CONFIRMED)),
            completed=Count("id", filter=Q(status=Booking.Status.COMPLETED)),
            completed_value=Sum(
                booking_price_field,
                filter=Q(status=Booking.Status.COMPLETED),
            ),
        )
        recent_bookings = (
            bookings.select_related("service", "customer", "slot", "service__store")
            .order_by("-created_at")[:100]
        )

        try:
            SlotModel = Booking._meta.get_field("slot").related_model
            assert SlotModel is not None
            upcoming_slots = (
                SlotModel.objects.filter(service__store=store, start_at__gte=now)
                .select_related("service")
                .order_by("start_at")[:6]
            )
        except Exception:
            upcoming_slots = []

    # Seven-day completed revenue trend
    daily_data = {}
    if is_product_business:
        daily_rows = (
            Order.objects.filter(
                store=store,
                status=Order.Status.COMPLETED,
                completed_at__isnull=False,
                completed_at__date__gte=first_day,
                completed_at__date__lte=today,
            )
            .annotate(day=TruncDate("completed_at"))
            .values("day")
            .annotate(value=Sum("total"), item_count=Count("id"))
            .order_by("day")
        )
        for row in daily_rows:
            daily_data[row["day"]] = {
                "value": row["value"] or ZERO,
                "count": row["item_count"],
            }
    elif is_service_business:
        booking_price_field = (
            "total"
            if hasattr(Booking, "total")
            else ("total_price" if hasattr(Booking, "total_price") else "service__price")
        )
        date_field = "completed_at" if hasattr(Booking, "completed_at") else "slot__start_at"
        daily_rows = (
            Booking.objects.filter(
                service__store=store,
                status=Booking.Status.COMPLETED,
                **{
                    f"{date_field}__isnull": False,
                    f"{date_field}__date__gte": first_day,
                    f"{date_field}__date__lte": today,
                },
            )
            .annotate(day=TruncDate(date_field))
            .values("day")
            .annotate(value=Sum(booking_price_field), item_count=Count("id"))
            .order_by("day")
        )
        for row in daily_rows:
            daily_data[row["day"]] = {
                "value": row["value"] or ZERO,
                "count": row["item_count"],
            }

    sales_chart = []
    for offset in range(7):
        day = first_day + timedelta(days=offset)
        day_data = daily_data.get(day, {"value": ZERO, "count": 0})
        sales_chart.append({
            "label": day.strftime("%a"),
            "date": day,
            "value": day_data["value"],
            "count": day_data["count"],
        })

    chart_max = max((item["value"] for item in sales_chart), default=ZERO)
    for item in sales_chart:
        if chart_max > ZERO and item["value"] > ZERO:
            item["bar_height"] = max(8, int((item["value"] / chart_max) * 100))
        else:
            item["bar_height"] = 2

    context = {
        "store": store,
        "business_mode": business_mode,
        "is_service_business": is_service_business,
        "is_product_business": is_product_business,

        # Product metrics
        "total_products": product_stats["total_count"] or 0,
        "available_products": product_stats["available_count"] or 0,
        "low_stock_products": low_stock_products,
        "total_orders": order_stats["total_count"] or 0,
        "pending_orders": order_stats["pending"] or 0,
        "processing_orders": order_stats["processing"] or 0,
        "completed_orders_count": order_stats["completed"] or 0,
        "completed_order_value": order_stats["completed_value"] or ZERO,
        "paid_order_value": order_stats["paid_value"] or ZERO,
        "recent_orders": recent_orders,

        # Service metrics
        "total_services": service_stats["total_count"] or 0,
        "available_services": service_stats["available_count"] or 0,
        "total_bookings": booking_stats["total_count"] or 0,
        "pending_bookings": booking_stats["pending"] or 0,
        "confirmed_bookings": booking_stats["confirmed"] or 0,
        "completed_bookings": booking_stats["completed"] or 0,
        "completed_booking_value": booking_stats["completed_value"] or ZERO,
        "recent_bookings": recent_bookings,
        "upcoming_slots": upcoming_slots,

        # Shared metrics
        "average_rating": review_stats["average"] or ZERO,
        "total_reviews": review_stats["review_count"] or 0,
        "unread_notifications": unread_notifications,
        "recent_notifications": recent_notifications,
        "recent_reviews": recent_reviews,
        "sales_chart": sales_chart,
        "today": today,
    }

    return render(request, "shopkeeper/home.html", context)



# --- OVERVIEW & NOTIFICATIONS ---
@login_required
def analytics_reports(request):
    context = {
        "page_title": "Analytics & Reports",
        "total_revenue": "12,450.00",
        "total_orders_or_bookings": 148,
        "conversion_rate": "4.2%",
    }
    return render(request, "shopkeeper/analytics.html", context)


@login_required
def notifications_list(request):
    """
    Displays all store notifications (orders, bookings, reviews, system updates)
    with category tabs, read/unread status, and DataTables search/sort.
    """
    store, redirect_response = _get_vendor_store(request.user)
    if redirect_response:
        return redirect_response

    category = request.GET.get("category", "all").strip().lower()
    base_qs = VendorNotification.objects.filter(store=store).select_related("order")

    counts = base_qs.aggregate(
        all=Count("id"),
        unread=Count("id", filter=Q(is_read=False)),
        orders=Count(
            "id",
            filter=Q(order__isnull=False) | Q(title__icontains="order"),
        ),
        bookings=Count("id", filter=Q(title__icontains="booking")),
        reviews=Count("id", filter=Q(title__icontains="review")),
    )

    notifications = base_qs.order_by("-created_at")

    if category == "unread":
        notifications = notifications.filter(is_read=False)
    elif category == "orders":
        notifications = notifications.filter(
            Q(order__isnull=False) | Q(title__icontains="order")
        )
    elif category == "bookings":
        notifications = notifications.filter(title__icontains="booking")
    elif category == "reviews":
        notifications = notifications.filter(title__icontains="review")

    context = {
        "store": store,
        "page_title": "Notifications",
        "notifications": notifications[:500],
        "category_filter": category,
        "counts": {
            "all": counts["all"] or 0,
            "unread": counts["unread"] or 0,
            "orders": counts["orders"] or 0,
            "bookings": counts["bookings"] or 0,
            "reviews": counts["reviews"] or 0,
        },
    }
    return render(request, "shopkeeper/notifications.html", context)


@login_required
@require_POST
def notification_mark_read(request, pk):
    """Marks a single notification as read and optionally redirects to its target."""
    store, redirect_response = _get_vendor_store(request.user)
    if redirect_response:
        return redirect_response

    notification = get_object_or_404(VendorNotification, store=store, pk=pk)
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read"])

    next_url = request.POST.get("next")
    if next_url:
        return redirect(next_url)

    return redirect("shopkeeper:notifications")


@login_required
@require_POST
def notification_mark_all_read(request):
    """Marks all unread notifications for the current store as read."""
    store, redirect_response = _get_vendor_store(request.user)
    if redirect_response:
        return redirect_response

    updated = VendorNotification.objects.filter(store=store, is_read=False).update(
        is_read=True
    )
    if updated:
        messages.success(request, f"Marked {updated} notification(s) as read.")
    else:
        messages.info(request, "All notifications are already read.")

    return redirect("shopkeeper:notifications")


@login_required
@require_POST
def notification_delete(request, pk):
    """Deletes a single notification."""
    store, redirect_response = _get_vendor_store(request.user)
    if redirect_response:
        return redirect_response

    notification = get_object_or_404(VendorNotification, store=store, pk=pk)
    notification.delete()
    messages.success(request, "Notification removed.")
    return redirect("shopkeeper:notifications")


# --- MY STORE ---
@login_required
def store_profile(request):
    if request.method == "POST":
        messages.success(request, "Store profile updated.")
        return redirect("shopkeeper:store_profile")
    return render(request, "shopkeeper/store/profile.html", {"page_title": "Store Profile"})


@login_required
def store_settings(request):
    if request.method == "POST":
        messages.success(request, "Store settings saved.")
        return redirect("shopkeeper:store_settings")
    return render(request, "shopkeeper/store/settings.html", {"page_title": "Store Settings"})


@login_required
def store_verification(request):
    if request.method == "POST":
        messages.success(request, "Verification documents submitted for review.")
        return redirect("shopkeeper:store_verification")
    return render(request, "shopkeeper/store/verification.html", {"page_title": "Business Verification"})


# --- PRODUCTS & INVENTORY ---
@login_required
def product_list(request, status="all"):
    titles = {"all": "All Products", "pending": "Product Approvals"}
    return render(request, "shopkeeper/products/list.html", {
        "page_title": titles.get(status, "Products"),
        "status_filter": status,
    })


@login_required
def product_create(request):
    if request.method == "POST":
        messages.success(request, "Product created and submitted for approval.")
        return redirect("shopkeeper:product_list")
    return render(request, "shopkeeper/products/form.html", {"page_title": "Add New Product"})



@login_required
def inventory_management(request):
    return render(request, "shopkeeper/products/inventory.html", {"page_title": "Inventory Management"})


# --- ORDERS ---
@login_required
def order_list(request, status="all"):
    """
    Lists store orders filtered by status ('all', 'pending', 'completed', 'cancelled')
    for client-side DataTables search, sort, and pagination.
    """
    store, redirect_response = _get_vendor_store(request.user)
    if redirect_response:
        return redirect_response

    titles = {
        "all": "All Orders",
        "pending": "Pending Orders",
        "completed": "Completed Orders",
        "cancelled": "Cancelled Orders",
    }

    base_orders = Order.objects.filter(store=store)

    counts = base_orders.aggregate(
        all=Count("id"),
        pending=Count("id", filter=Q(status=Order.Status.PENDING)),
        in_progress=Count(
            "id",
            filter=Q(
                status__in=[
                    Order.Status.CONFIRMED,
                    Order.Status.PREPARING,
                    Order.Status.READY,
                ]
            ),
        ),
        completed=Count("id", filter=Q(status=Order.Status.COMPLETED)),
        cancelled=Count(
            "id",
            filter=Q(status__in=[Order.Status.CANCELLED, Order.Status.REJECTED]),
        ),
        completed_revenue=Sum("total", filter=Q(status=Order.Status.COMPLETED)),
    )

    orders = (
        base_orders.select_related("customer")
        .prefetch_related("items")
        .order_by("-created_at")
    )

    if status == "pending":
        orders = orders.filter(status=Order.Status.PENDING)
    elif status == "completed":
        orders = orders.filter(status=Order.Status.COMPLETED)
    elif status == "cancelled":
        orders = orders.filter(
            status__in=[Order.Status.CANCELLED, Order.Status.REJECTED]
        )

    fulfilment_filter = request.GET.get("fulfilment", "").strip()
    payment_filter = request.GET.get("payment", "").strip()

    if fulfilment_filter in dict(Order.Fulfilment.choices):
        orders = orders.filter(fulfilment_method=fulfilment_filter)

    if payment_filter in dict(Order.PaymentStatus.choices):
        orders = orders.filter(payment_status=payment_filter)

    context = {
        "store": store,
        "page_title": titles.get(status, "Orders"),
        "status_filter": status,
        "orders": orders[:500],
        "counts": {
            "all": counts["all"] or 0,
            "pending": counts["pending"] or 0,
            "in_progress": counts["in_progress"] or 0,
            "completed": counts["completed"] or 0,
            "cancelled": counts["cancelled"] or 0,
            "completed_revenue": counts["completed_revenue"] or ZERO,
        },
        "fulfilment_filter": fulfilment_filter,
        "payment_filter": payment_filter,
        "fulfilment_choices": Order.Fulfilment.choices,
        "payment_choices": Order.PaymentStatus.choices,
    }
    return render(request, "shopkeeper/orders/list.html", context)


@login_required
@require_POST
def order_update_status(request, order_number):
    """
    Transitions an order to a valid next status using Order.change_status().
    """
    store, redirect_response = _get_vendor_store(request.user)
    if redirect_response:
        return redirect_response

    order = get_object_or_404(Order, store=store, order_number=order_number)
    new_status = request.POST.get("new_status", "").strip()
    note = request.POST.get("note", "").strip()

    try:
        order.change_status(new_status=new_status, by=request.user, note=note)
        messages.success(
            request,
            f"Order #{order.order_number} updated to {order.get_status_display()}.",
        )
    except ValidationError as exc:
        messages.error(request, exc.message)

    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER")
    if next_url:
        return redirect(next_url)
    return redirect("shopkeeper:order_list")


# --- SERVICES ---
@login_required
def service_list(request, status="all"):
    titles = {"all": "All Services", "pending": "Service Approvals"}
    return render(request, "shopkeeper/services/list.html", {
        "page_title": titles.get(status, "Services"),
        "status_filter": status,
    })


@login_required
def service_create(request):
    if request.method == "POST":
        messages.success(request, "Service created and submitted for approval.")
        return redirect("shopkeeper:service_list")
    return render(request, "shopkeeper/services/form.html", {"page_title": "Add New Service"})


@login_required
def service_categories(request):
    return render(request, "shopkeeper/categories.html", {
        "page_title": "Service Categories",
        "category_type": "Service",
    })


# --- BOOKINGS & SCHEDULE ---
@login_required
def booking_list(request, status="all"):
    """
    Lists store service bookings filtered by status ('all', 'pending', 'confirmed',
    'completed', 'cancelled') for client-side DataTables search, sort, and pagination.
    """
    store, redirect_response = _get_vendor_store(request.user)
    if redirect_response:
        return redirect_response

    titles = {
        "all": "All Bookings",
        "pending": "Pending Booking Requests",
        "confirmed": "Confirmed Bookings",
        "completed": "Completed Bookings",
        "cancelled": "Cancelled & Rejected Bookings",
    }

    base_bookings = Booking.objects.filter(service__store=store)

    # Summary counts for tabs & KPI strip
    counts = base_bookings.aggregate(
        all=Count("id"),
        pending=Count("id", filter=Q(status=Booking.Status.PENDING)),
        confirmed=Count("id", filter=Q(status=Booking.Status.CONFIRMED)),
        completed=Count("id", filter=Q(status=Booking.Status.COMPLETED)),
        cancelled=Count(
            "id",
            filter=Q(
                status__in=[
                    Booking.Status.CANCELLED_BY_CUSTOMER,
                    Booking.Status.CANCELLED_BY_VENDOR,
                    Booking.Status.REJECTED,
                    Booking.Status.NO_SHOW,
                ]
            ),
        ),
        completed_revenue=Sum("total_price", filter=Q(status=Booking.Status.COMPLETED)),
    )

    bookings = (
        base_bookings.select_related("customer", "service", "slot")
        .order_by("-created_at")
    )

    # Apply tab status filter
    if status == "pending":
        bookings = bookings.filter(status=Booking.Status.PENDING)
    elif status == "confirmed":
        bookings = bookings.filter(status=Booking.Status.CONFIRMED)
    elif status == "completed":
        bookings = bookings.filter(status=Booking.Status.COMPLETED)
    elif status == "cancelled":
        bookings = bookings.filter(
            status__in=[
                Booking.Status.CANCELLED_BY_CUSTOMER,
                Booking.Status.CANCELLED_BY_VENDOR,
                Booking.Status.REJECTED,
                Booking.Status.NO_SHOW,
            ]
        )

    # Optional service & schedule timeframe filters
    service_filter = request.GET.get("service", "").strip()
    timeframe_filter = request.GET.get("timeframe", "").strip()
    now = timezone.now()

    if service_filter.isdigit():
        bookings = bookings.filter(service_id=int(service_filter))

    if timeframe_filter == "upcoming":
        bookings = bookings.filter(slot__start_at__gte=now)
    elif timeframe_filter == "past":
        bookings = bookings.filter(slot__start_at__lt=now)

    store_services = Service.objects.filter(store=store).order_by("name")

    context = {
        "store": store,
        "page_title": titles.get(status, "Bookings"),
        "status_filter": status,
        "bookings": bookings[:500],
        "counts": {
            "all": counts["all"] or 0,
            "pending": counts["pending"] or 0,
            "confirmed": counts["confirmed"] or 0,
            "completed": counts["completed"] or 0,
            "cancelled": counts["cancelled"] or 0,
            "completed_revenue": counts["completed_revenue"] or ZERO,
        },
        "store_services": store_services,
        "service_filter": service_filter,
        "timeframe_filter": timeframe_filter,
        "now": now,
    }
    return render(request, "shopkeeper/bookings/list.html", context)


@login_required
@require_POST
def booking_update_status(request, reference):
    """
    Executes valid vendor transitions on a Booking using its domain methods
    (approve, reject, cancel_by_vendor, complete, mark_no_show).
    """
    store, redirect_response = _get_vendor_store(request.user)
    if redirect_response:
        return redirect_response

    booking = get_object_or_404(
        Booking.objects.select_related("service", "slot"),
        service__store=store,
        reference=reference,
    )
    action = request.POST.get("action", "").strip()
    note = request.POST.get("note", "").strip()

    try:
        if action == "approve":
            booking.approve(note=note)
            messages.success(request, f"Booking {booking.reference} confirmed.")
        elif action == "reject":
            booking.reject(reason=note)
            messages.warning(request, f"Booking {booking.reference} rejected.")
        elif action == "cancel":
            booking.cancel_by_vendor(reason=note)
            messages.warning(request, f"Booking {booking.reference} cancelled.")
        elif action == "complete":
            booking.complete()
            messages.success(request, f"Booking {booking.reference} marked as completed.")
        elif action == "no_show":
            booking.mark_no_show()
            messages.info(request, f"Booking {booking.reference} marked as no-show.")
        else:
            messages.error(request, "Invalid booking action.")
    except ValidationError as exc:
        messages.error(request, exc.message)

    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER")
    if next_url:
        return redirect(next_url)
    return redirect("shopkeeper:booking_list")

@login_required
def manage_slots(request):
    return render(request, "shopkeeper/schedule/manage_slots.html", {"page_title": "Manage Time Slots"})


@login_required
def create_slots(request):
    if request.method == "POST":
        messages.success(request, "Time slots generated successfully.")
        return redirect("shopkeeper:manage_slots")
    return render(request, "shopkeeper/schedule/create_slots.html", {"page_title": "Create Time Slots"})


@login_required
def working_hours(request):
    if request.method == "POST":
        messages.success(request, "Working hours updated.")
        return redirect("shopkeeper:working_hours")
    return render(request, "shopkeeper/schedule/working_hours.html", {"page_title": "Working Hours"})


# --- SALES & CRM ---
@login_required
def sales_list(request):
    """
    Unified sales ledger combining completed Orders and completed Bookings,
    including a Chart.js comparison against the previous period and receipt downloads.
    """
    store, redirect_response = _get_vendor_store(request.user)
    if redirect_response:
        return redirect_response

    business_mode = _resolve_business_mode(store)
    is_service_business = business_mode in ("service", "both")
    is_product_business = business_mode in ("product", "both")

    period = request.GET.get("period", "7d").strip().lower()
    type_filter = request.GET.get("type", "all").strip().lower()

    now = timezone.now()
    today = timezone.localdate()
    tz = timezone.get_current_timezone()

    def _day_start(d):
        return timezone.make_aware(datetime.combine(d, time.min), tz)

    # Determine current window, previous comparison window, and bucket granularity
    if period == "today":
        curr_start = _day_start(today)
        curr_end = now
        prev_start = _day_start(today - timedelta(days=1))
        prev_end = curr_start
        bucket_mode = "hour"
        num_buckets = 24
        curr_label = "Today"
        prev_label = "Yesterday"
    elif period == "30d":
        curr_start = _day_start(today - timedelta(days=29))
        curr_end = now
        prev_start = _day_start(today - timedelta(days=59))
        prev_end = curr_start
        bucket_mode = "day"
        num_buckets = 30
        curr_label = "Last 30 Days"
        prev_label = "Previous 30 Days"
    elif period == "month":
        first_of_month = today.replace(day=1)
        last_month_end_date = first_of_month - timedelta(days=1)
        last_month_start_date = last_month_end_date.replace(day=1)
        curr_start = _day_start(first_of_month)
        curr_end = now
        prev_start = _day_start(last_month_start_date)
        prev_end = curr_start
        bucket_mode = "dom"  # Day of month (1..31)
        num_buckets = 31
        curr_label = today.strftime("%B %Y")
        prev_label = last_month_start_date.strftime("%B %Y")
    elif period == "all":
        # Compare last 6 months vs preceding 6 months on chart, show all rows in table
        curr_start = None
        curr_end = now
        prev_start = None
        prev_end = None
        bucket_mode = "month"
        num_buckets = 6
        curr_label = "Last 6 Months"
        prev_label = "Prior 6 Months"
    else:
        period = "7d"
        curr_start = _day_start(today - timedelta(days=6))
        curr_end = now
        prev_start = _day_start(today - timedelta(days=13))
        prev_end = curr_start
        bucket_mode = "day"
        num_buckets = 7
        curr_label = "Last 7 Days"
        prev_label = "Previous 7 Days"

    # Fetch base completed records (we fetch back to prev_start for comparison)
    orders_all = Order.objects.none()
    bookings_all = Booking.objects.none()

    if is_product_business and type_filter in ("all", "order"):
        orders_all = (
            Order.objects.filter(store=store, status=Order.Status.COMPLETED)
            .select_related("customer")
            .prefetch_related("items")
        )
        if prev_start:
            orders_all = orders_all.filter(completed_at__gte=prev_start)

    if is_service_business and type_filter in ("all", "booking"):
        bookings_all = Booking.objects.filter(
            service__store=store, status=Booking.Status.COMPLETED
        ).select_related("customer", "service", "slot")
        if prev_start:
            bookings_all = bookings_all.filter(completed_at__gte=prev_start)

    # Build comparison buckets
    curr_series = [ZERO] * num_buckets
    prev_series = [ZERO] * num_buckets

    if bucket_mode == "hour":
        chart_labels = [f"{h:02d}:00" for h in range(24)]
    elif bucket_mode == "day":
        chart_labels = [
            (today - timedelta(days=(num_buckets - 1 - i))).strftime("%b %d")
            for i in range(num_buckets)
        ]
    elif bucket_mode == "dom":
        chart_labels = [f"Day {d}" for d in range(1, 32)]
    else:
        # 6-month rolling comparison for "all"
        chart_labels = []
        for offset in range(5, -1, -1):
            m_date = (today.replace(day=1) - timedelta(days=offset * 28)).replace(day=1)
            chart_labels.append(m_date.strftime("%b %Y"))

    def _add_to_series(dt, amount):
        if not dt:
            return
        local_dt = timezone.localtime(dt, tz)

        if bucket_mode == "hour":
            if curr_start <= dt <= curr_end:
                curr_series[local_dt.hour] += amount
            elif prev_start <= dt < prev_end:
                prev_series[local_dt.hour] += amount

        elif bucket_mode == "day":
            if curr_start <= dt <= curr_end:
                assert curr_start is not None
                idx = (local_dt.date() - curr_start.date()).days
                if 0 <= idx < num_buckets:
                    curr_series[idx] += amount
            elif prev_start <= dt < prev_end:
                assert prev_start is not None
                idx = (local_dt.date() - prev_start.date()).days
                if 0 <= idx < num_buckets:
                    prev_series[idx] += amount

        elif bucket_mode == "dom":
            idx = local_dt.day - 1
            if 0 <= idx < 31:
                if curr_start <= dt <= curr_end:
                    curr_series[idx] += amount
                elif prev_start <= dt < prev_end:
                    prev_series[idx] += amount

        elif bucket_mode == "month":
            months_ago = (today.year - local_dt.year) * 12 + (today.month - local_dt.month)
            if 0 <= months_ago < 6:
                curr_series[5 - months_ago] += amount
            elif 6 <= months_ago < 12:
                prev_series[11 - months_ago] += amount

    sales = []
    product_revenue = ZERO
    service_revenue = ZERO
    previous_period_revenue = ZERO

    # Process Orders
    for order in orders_all:
        sale_date = order.completed_at or order.created_at
        _add_to_series(sale_date, order.total)

        if prev_start and prev_start <= sale_date < prev_end:
            previous_period_revenue += order.total
            continue

        if curr_start and sale_date < curr_start:
            continue

        product_revenue += order.total
        customer_name = (
            order.customer_name
            or (order.customer.get_full_name() if order.customer else "")
            or "Guest Customer"
        )
        sales.append({
            "id": f"order-{order.id}",
            "pk": order.id,
            "reference": f"#{order.order_number}",
            "type": "Product Order",
            "type_key": "order",
            "customer_name": customer_name,
            "customer_phone": order.customer_phone,
            "customer_email": order.customer_email,
            "summary": f"{order.item_count} item(s) · {order.get_fulfilment_method_display()}",
            "payment_method": order.get_payment_method_display(),
            "payment_status": order.get_payment_status_display(),
            "is_paid": order.payment_status == Order.PaymentStatus.PAID,
            "amount": order.total,
            "date": sale_date,
            "order": order,
            "booking": None,
        })

    # Process Bookings
    for booking in bookings_all:
        sale_date = booking.completed_at or booking.slot.start_at
        _add_to_series(sale_date, booking.total_price)

        if prev_start and prev_start <= sale_date < prev_end:
            previous_period_revenue += booking.total_price
            continue

        if curr_start and sale_date < curr_start:
            continue

        service_revenue += booking.total_price
        customer_name = booking.customer.get_full_name() or booking.customer.email
        sales.append({
            "id": f"booking-{booking.id}", # type: ignore
            "pk": booking.id, # type: ignore
            "reference": booking.reference,
            "type": "Service Booking",
            "type_key": "booking",
            "customer_name": customer_name,
            "customer_phone": booking.customer_phone,
            "customer_email": booking.customer.email,
            "summary": f"{booking.service.name} ({booking.seats} seat(s))",
            "payment_method": "Service Booking",
            "payment_status": "Completed",
            "is_paid": True,
            "amount": booking.total_price,
            "date": sale_date,
            "order": None,
            "booking": booking,
        })

    sales.sort(key=lambda s: s["date"], reverse=True)

    total_revenue = product_revenue + service_revenue
    if period == "all":
        previous_period_revenue = sum(prev_series, ZERO)
        comparison_current = sum(curr_series, ZERO)
        growth_pct = _pct_change(comparison_current, previous_period_revenue) # type: ignore
    else:
        growth_pct = _pct_change(total_revenue, previous_period_revenue) # type: ignore

    sales_count = len(sales)
    avg_sale = (total_revenue / sales_count) if sales_count else ZERO

    chart_payload = {
        "labels": chart_labels,
        "current_label": curr_label,
        "previous_label": prev_label,
        "current_data": [float(v) for v in curr_series],
        "previous_data": [float(v) for v in prev_series],
    }

    context = {
        "store": store,
        "page_title": "Sales Management",
        "business_mode": business_mode,
        "is_service_business": is_service_business,
        "is_product_business": is_product_business,
        "sales": sales,
        "period_filter": period,
        "type_filter": type_filter,
        "chart_payload_json": json.dumps(chart_payload),
        "curr_label": curr_label,
        "prev_label": prev_label,
        "stats": {
            "total_revenue": total_revenue,
            "previous_revenue": previous_period_revenue,
            "growth_pct": growth_pct,
            "product_revenue": product_revenue,
            "service_revenue": service_revenue,
            "sales_count": sales_count,
            "avg_sale": avg_sale,
        },
    }
    return render(request, "shopkeeper/sales/list.html", context)


@login_required
def sale_receipt(request, sale_type, pk):
    """
    Renders a printable receipt for a completed Order or Booking.
    Supports `?download=1` to download a standalone HTML receipt file,
    or `?print=1` to immediately trigger the browser Print / Save as PDF dialog.
    """
    store, redirect_response = _get_vendor_store(request.user)
    if redirect_response:
        return redirect_response

    order = None
    booking = None

    if sale_type == "order":
        order = get_object_or_404(
            Order.objects.select_related("customer").prefetch_related("items"),
            store=store,
            pk=pk,
        )
        reference = order.order_number
        sale_date = order.completed_at or order.created_at
        customer_name = (
            order.customer_name
            or (order.customer.get_full_name() if order.customer else "")
            or "Guest Customer"
        )
        customer_phone = order.customer_phone
        customer_email = order.customer_email
        total_amount = order.total
    elif sale_type == "booking":
        booking = get_object_or_404(
            Booking.objects.select_related("customer", "service", "slot"),
            service__store=store,
            pk=pk,
        )
        reference = booking.reference
        sale_date = booking.completed_at or booking.slot.start_at
        customer_name = booking.customer.get_full_name() or booking.customer.email
        customer_phone = booking.customer_phone
        customer_email = booking.customer.email
        total_amount = booking.total_price
    else:
        return HttpResponse("Invalid receipt type.", status=400)

    context = {
        "store": store,
        "sale_type": sale_type,
        "reference": reference,
        "sale_date": sale_date,
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        "customer_email": customer_email,
        "total_amount": total_amount,
        "order": order,
        "booking": booking,
        "auto_print": request.GET.get("print") == "1",
        "is_download": request.GET.get("download") == "1",
    }

    if request.GET.get("download") == "1":
        html_content = render_to_string("shopkeeper/sales/receipt.html", context, request=request)
        response = HttpResponse(html_content, content_type="text/html; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="Receipt-{reference}.html"'
        return response

    return render(request, "shopkeeper/sales/receipt.html", context)


@login_required
def customers_list(request):
    """
    Aggregates unique customers & clients across store Orders and Bookings,
    computing total completed spend, order/booking counts, and last activity.
    """
    store, redirect_response = _get_vendor_store(request.user)
    if redirect_response:
        return redirect_response

    business_mode = _resolve_business_mode(store)
    is_service_business = business_mode in ("service", "both")
    is_product_business = business_mode in ("product", "both")

    page_title = (
        "Clients"
        if (is_service_business and not is_product_business)
        else "Customers"
    )

    directory = {}

    def _get_or_create_entry(key, full_name, email, phone, is_registered=False):
        if key not in directory:
            directory[key] = {
                "key": key,
                "full_name": full_name or "Guest Customer",
                "email": email or "",
                "phone": phone or "",
                "is_registered": is_registered,
                "order_count": 0,
                "booking_count": 0,
                "total_count": 0,
                "total_spent": ZERO,
                "last_activity": None,
            }
        else:
            entry = directory[key]
            if not entry["email"] and email:
                entry["email"] = email
            if not entry["phone"] and phone:
                entry["phone"] = phone
            if entry["full_name"] == "Guest Customer" and full_name:
                entry["full_name"] = full_name
        return directory[key]

    # 1. Aggregate from Orders (exclude rejected/cancelled from spend, count valid orders)
    if is_product_business:
        orders = (
            Order.objects.filter(store=store)
            .exclude(status__in=[Order.Status.CANCELLED, Order.Status.REJECTED])
            .select_related("customer")
        )
        for order in orders:
            if order.customer_id:
                key = f"user-{order.customer_id}"
                name = (
                    order.customer.get_full_name()
                    or order.customer_name
                    or order.customer.email
                )
                email = order.customer.email or order.customer_email
                is_reg = True
            else:
                identifier = (
                    order.customer_email.lower().strip()
                    or order.customer_phone.strip()
                    or order.customer_name.lower().strip()
                    or f"guest-order-{order.id}"
                )
                key = f"guest-{identifier}"
                name = order.customer_name or "Guest Customer"
                email = order.customer_email
                is_reg = False

            entry = _get_or_create_entry(
                key, name, email, order.customer_phone, is_registered=is_reg
            )
            entry["order_count"] += 1
            entry["total_count"] += 1
            if order.status == Order.Status.COMPLETED:
                entry["total_spent"] += order.total
            if not entry["last_activity"] or order.created_at > entry["last_activity"]:
                entry["last_activity"] = order.created_at

    # 2. Aggregate from Bookings
    if is_service_business:
        bookings = (
            Booking.objects.filter(service__store=store)
            .exclude(
                status__in=[
                    Booking.Status.REJECTED,
                    Booking.Status.CANCELLED_BY_CUSTOMER,
                    Booking.Status.CANCELLED_BY_VENDOR,
                ]
            )
            .select_related("customer")
        )
        for booking in bookings:
            key = f"user-{booking.customer_id}"
            name = booking.customer.get_full_name() or booking.customer.email
            entry = _get_or_create_entry(
                key,
                name,
                booking.customer.email,
                booking.customer_phone,
                is_registered=True,
            )
            entry["booking_count"] += 1
            entry["total_count"] += 1
            if booking.status == Booking.Status.COMPLETED:
                entry["total_spent"] += booking.total_price
            if not entry["last_activity"] or booking.created_at > entry["last_activity"]:
                entry["last_activity"] = booking.created_at

    customers = sorted(
        directory.values(),
        key=lambda c: (c["total_spent"], c["total_count"]),
        reverse=True,
    )

    repeat_customers = sum(1 for c in customers if c["total_count"] > 1)
    total_customer_spend = sum((c["total_spent"] for c in customers), ZERO)

    context = {
        "store": store,
        "page_title": page_title,
        "business_mode": business_mode,
        "is_service_business": is_service_business,
        "is_product_business": is_product_business,
        "customers": customers,
        "stats": {
            "total_customers": len(customers),
            "repeat_customers": repeat_customers,
            "total_customer_spend": total_customer_spend,
        },
    }
    return render(request, "shopkeeper/customers.html", context)

# --- MARKETING & PROMOTION ---
@login_required
def ad_campaigns(request, status="all"):
    titles = {"all": "My Campaigns", "pending": "Ad Approvals"}
    return render(request, "shopkeeper/marketing/ads_list.html", {
        "page_title": titles.get(status, "Advertisements"),
        "status_filter": status,
    })


@login_required
def ad_create(request):
    if request.method == "POST":
        messages.success(request, "Advertisement submitted for approval.")
        return redirect("shopkeeper:ad_campaigns")
    return render(request, "shopkeeper/marketing/ad_form.html", {"page_title": "Create Advertisement"})


@login_required
def ad_performance(request):
    return render(request, "shopkeeper/marketing/ad_performance.html", {"page_title": "Ad Performance"})


@login_required
def promotions_coupons(request):
    return render(request, "shopkeeper/marketing/promotions.html", {"page_title": "Promotions & Coupons"})


@login_required
def featured_listings(request):
    return render(request, "shopkeeper/marketing/featured.html", {"page_title": "Featured Listings"})


@login_required
def announcements(request):
    return render(request, "shopkeeper/marketing/announcements.html", {"page_title": "Platform Announcements"})


# --- FINANCIAL MANAGEMENT ---
@login_required
def earnings_overview(request):
    return render(request, "shopkeeper/finance/earnings.html", {"page_title": "Earnings Overview"})


@login_required
def payout_history(request):
    return render(request, "shopkeeper/finance/payouts.html", {"page_title": "Payout History"})



@login_required
def my_subscription(request):
    return render(request, "shopkeeper/subscriptions/my_plan.html", {"page_title": "My Subscription"})


@login_required
def available_plans(request):
    return render(request, "shopkeeper/subscriptions/plans.html", {"page_title": "Available Plans"})


@login_required
def billing_history(request):
    return render(request, "shopkeeper/subscriptions/billing.html", {"page_title": "Billing History"})


@login_required
def invoices_list(request):
    return render(request, "shopkeeper/subscriptions/invoices.html", {"page_title": "Invoices"})


@login_required
def transactions_list(request):
    """
    Unified financial ledger (credits and debits) across paid/refunded orders,
    completed bookings, and platform payouts/fees, with CSV export and DataTables.
    """
    store, redirect_response = _get_vendor_store(request.user)
    if redirect_response:
        return redirect_response

    business_mode = _resolve_business_mode(store)
    is_service_business = business_mode in ("service", "both")
    is_product_business = business_mode in ("product", "both")

    entry_filter = request.GET.get("entry", "all").strip().lower()
    method_filter = request.GET.get("method", "all").strip().lower()

    transactions = []
    total_credits = ZERO
    total_debits = ZERO

    # 1. Product Orders (Paid = Credit, Refunded = Debit)
    if is_product_business:
        orders_qs = Order.objects.filter(
            store=store,
            payment_status__in=[Order.PaymentStatus.PAID, Order.PaymentStatus.REFUNDED],
        ).select_related("customer")

        for order in orders_qs:
            customer_label = (
                order.customer_name
                or (order.customer.get_full_name() if order.customer else "")
                or "Guest Customer"
            )
            txn_ref = order.payment_reference or f"TXN-{order.order_number}"
            txn_date = order.completed_at or order.updated_at or order.created_at

            if order.payment_status == Order.PaymentStatus.PAID:
                total_credits += order.total
                transactions.append({
                    "reference": txn_ref,
                    "source_ref": f"#{order.order_number}",
                    "description": f"Order payment from {customer_label}",
                    "entry_type": "Credit",
                    "is_credit": True,
                    "category": "Order Payment",
                    "payment_method": order.get_payment_method_display(),
                    "method_key": order.payment_method,
                    "amount": order.total,
                    "created_at": txn_date,
                })
            elif order.payment_status == Order.PaymentStatus.REFUNDED:
                total_debits += order.total
                transactions.append({
                    "reference": f"RFD-{order.order_number}",
                    "source_ref": f"#{order.order_number}",
                    "description": f"Refund issued to {customer_label}",
                    "entry_type": "Debit",
                    "is_credit": False,
                    "category": "Order Refund",
                    "payment_method": order.get_payment_method_display(),
                    "method_key": order.payment_method,
                    "amount": order.total,
                    "created_at": order.cancelled_at or txn_date,
                })

    # 2. Service Bookings (Completed = Credit)
    if is_service_business:
        bookings_qs = Booking.objects.filter(
            service__store=store,
            status=Booking.Status.COMPLETED,
        ).select_related("customer", "service", "slot")

        for booking in bookings_qs:
            client_label = booking.customer.get_full_name() or booking.customer.email
            txn_date = booking.completed_at or booking.slot.start_at
            total_credits += booking.total_price
            transactions.append({
                "reference": f"TXN-{booking.reference}",
                "source_ref": booking.reference,
                "description": f"Booking payment — {booking.service.name} ({client_label})",
                "entry_type": "Credit",
                "is_credit": True,
                "category": "Booking Payment",
                "payment_method": "Booking Settlement",
                "method_key": "booking",
                "amount": booking.total_price,
                "created_at": txn_date,
            })

    # Optional: include Subscription / Commission payouts if the model exists in your project
    try:
        from subscriptions.models import VendorPayout  # adjust app path if applicable

        for payout in VendorPayout.objects.filter(store=store):
            payout_amt = getattr(payout, "amount", ZERO) or ZERO
            total_debits += payout_amt
            transactions.append({
                "reference": getattr(payout, "reference", f"PAY-{payout.pk}"),
                "source_ref": "Platform",
                "description": getattr(payout, "description", "Monthly subscription / commission settlement"),
                "entry_type": "Debit",
                "is_credit": False,
                "category": "Platform Fee",
                "payment_method": "Platform Billing",
                "method_key": "platform",
                "amount": payout_amt,
                "created_at": payout.created_at,
            })
    except Exception:
        pass

    # Sort newest first
    transactions.sort(key=lambda t: t["created_at"], reverse=True)

    # Apply entry type & method filters
    if entry_filter == "credit":
        transactions = [t for t in transactions if t["is_credit"]]
    elif entry_filter == "debit":
        transactions = [t for t in transactions if not t["is_credit"]]

    if method_filter != "all":
        transactions = [t for t in transactions if t["method_key"] == method_filter]

    net_balance = total_credits - total_debits

    # CSV Export support (?export=csv)
    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        assert store is not None
        response["Content-Disposition"] = f'attachment; filename="{store.slug or "store"}-transactions.csv"'
        writer = csv.writer(response)
        writer.writerow(["Txn ID", "Source Ref", "Description", "Category", "Type", "Method", "Amount (Rs)", "Date"])
        for txn in transactions:
            signed_amt = txn["amount"] if txn["is_credit"] else -txn["amount"]
            writer.writerow([
                txn["reference"],
                txn["source_ref"],
                txn["description"],
                txn["category"],
                txn["entry_type"],
                txn["payment_method"],
                f"{signed_amt:.2f}",
                txn["created_at"].strftime("%Y-%m-%d %H:%M"),
            ])
        return response

    context = {
        "store": store,
        "page_title": "Transactions",
        "transactions": transactions,
        "entry_filter": entry_filter,
        "method_filter": method_filter,
        "payment_methods": Order.PaymentMethod.choices,
        "stats": {
            "total_credits": total_credits,
            "total_debits": total_debits,
            "net_balance": net_balance,
            "txn_count": len(transactions),
        },
    }
    return render(request, "shopkeeper/finance/transactions.html", context)

# --- COMMUNICATION ---
@login_required
def reviews_list(request):
    """
    Store review analytics, 1-5 star breakdown, monthly rating trends,
    top/lowest-rated item breakdown, and DataTables management with vendor replies.
    """
    store, redirect_response = _get_vendor_store(request.user)
    if redirect_response:
        return redirect_response

    rating_filter = request.GET.get("rating", "all").strip()
    reply_filter = request.GET.get("reply", "all").strip().lower()
    status_filter = request.GET.get("status", "all").strip().lower()

    all_reviews = Review.objects.filter(store=store).select_related(
        "author",
        "product",
        "service",
        "order_item__order",
        "booking__slot",
        "replied_by",
    )
    published_reviews = all_reviews.filter(status=Review.Status.PUBLISHED)

    # Core KPIs (calculated from published reviews)
    agg = published_reviews.aggregate(
        avg_rating=Avg("overall_rating"),
        total_published=Count("id"),
        r5=Count("id", filter=Q(overall_rating=5)),
        r4=Count("id", filter=Q(overall_rating=4)),
        r3=Count("id", filter=Q(overall_rating=3)),
        r2=Count("id", filter=Q(overall_rating=2)),
        r1=Count("id", filter=Q(overall_rating=1)),
        replied_count=Count("id", filter=~Q(reply_text="")),
        positive_count=Count("id", filter=Q(overall_rating__gte=4)),
        product_reviews_count=Count("id", filter=Q(order_item__isnull=False)),
        booking_reviews_count=Count("id", filter=Q(booking__isnull=False)),
    )

    total_published = agg["total_published"] or 0
    avg_rating = round(Decimal(str(agg["avg_rating"] or 0)), 2)
    replied_count = agg["replied_count"] or 0
    unreplied_count = max(total_published - replied_count, 0)
    response_rate = (
        round((replied_count / total_published) * 100, 1) if total_published else 0
    )
    positive_rate = (
        round(((agg["positive_count"] or 0) / total_published) * 100, 1)
        if total_published
        else 0
    )
    hidden_count = all_reviews.filter(status=Review.Status.HIDDEN).count()

    # 5-star to 1-star breakdown rows for progress bars + doughnut chart
    star_breakdown = []
    for star in (5, 4, 3, 2, 1):
        count = agg[f"r{star}"] or 0
        pct = round((count / total_published) * 100, 1) if total_published else 0
        star_breakdown.append({
            "star": star,
            "count": count,
            "pct": pct,
        })

    # Per-Product & Per-Service Breakdown (Top / Lowest rated offerings)
    item_breakdown = []
    product_groups = (
        published_reviews.filter(product__isnull=False)
        .values("product_id", "product__name")
        .annotate(avg=Avg("overall_rating"), count=Count("id"))
        .order_by("-count", "-avg")
    )
    for row in product_groups:
        item_breakdown.append({
            "name": row["product__name"],
            "type": "Product",
            "avg": round(Decimal(str(row["avg"])), 2),
            "count": row["count"],
        })

    service_groups = (
        published_reviews.filter(service__isnull=False)
        .values("service_id", "service__name")
        .annotate(avg=Avg("overall_rating"), count=Count("id"))
        .order_by("-count", "-avg")
    )
    for row in service_groups:
        item_breakdown.append({
            "name": row["service__name"],
            "type": "Service",
            "avg": round(Decimal(str(row["avg"])), 2),
            "count": row["count"],
        })

    item_breakdown.sort(key=lambda x: (x["count"], x["avg"]), reverse=True)

    # 6-Month Rating & Review Volume Trend (for Chart.js)
    today = timezone.localdate()
    six_months_ago = (today.replace(day=1) - timedelta(days=150)).replace(day=1)
    monthly_rows = (
        published_reviews.filter(created_at__date__gte=six_months_ago)
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(avg_rating=Avg("overall_rating"), count=Count("id"))
        .order_by("month")
    )
    monthly_map = {
        row["month"].date().replace(day=1): {
            "avg": round(float(row["avg_rating"]), 2),
            "count": row["count"],
        }
        for row in monthly_rows
        if row["month"]
    }

    month_labels = []
    month_counts = []
    month_avgs = []
    for offset in range(5, -1, -1):
        m_date = (today.replace(day=1) - timedelta(days=offset * 28)).replace(day=1)
        month_labels.append(m_date.strftime("%b %Y"))
        entry = monthly_map.get(m_date, {"avg": 0, "count": 0})
        month_counts.append(entry["count"])
        month_avgs.append(entry["avg"])

    chart_payload = {
        "star_labels": ["5 ★", "4 ★", "3 ★", "2 ★", "1 ★"],
        "star_counts": [agg["r5"] or 0, agg["r4"] or 0, agg["r3"] or 0, agg["r2"] or 0, agg["r1"] or 0],
        "month_labels": month_labels,
        "month_counts": month_counts,
        "month_avgs": month_avgs,
    }

    # Filtered queryset for DataTables
    reviews = all_reviews.order_by("-created_at")

    if rating_filter in ("1", "2", "3", "4", "5"):
        reviews = reviews.filter(overall_rating=int(rating_filter))

    if reply_filter == "unreplied":
        reviews = reviews.filter(reply_text="")
    elif reply_filter == "replied":
        reviews = reviews.exclude(reply_text="")

    if status_filter == "published":
        reviews = reviews.filter(status=Review.Status.PUBLISHED)
    elif status_filter == "hidden":
        reviews = reviews.filter(status=Review.Status.HIDDEN)

    context = {
        "store": store,
        "page_title": "Reviews & Ratings",
        "reviews": reviews[:500],
        "rating_filter": rating_filter,
        "reply_filter": reply_filter,
        "status_filter": status_filter,
        "star_breakdown": star_breakdown,
        "item_breakdown": item_breakdown[:8],
        "chart_payload_json": json.dumps(chart_payload),
        "stats": {
            "avg_rating": avg_rating,
            "total_published": total_published,
            "replied_count": replied_count,
            "unreplied_count": unreplied_count,
            "response_rate": response_rate,
            "positive_rate": positive_rate,
            "hidden_count": hidden_count,
            "product_reviews_count": agg["product_reviews_count"] or 0,
            "booking_reviews_count": agg["booking_reviews_count"] or 0,
        },
    }
    return render(request, "shopkeeper/communication/reviews.html", context)


@login_required
@require_POST
def review_reply(request, pk):
    """Adds, updates, or removes a vendor reply using Review.add_reply / remove_reply."""
    store, redirect_response = _get_vendor_store(request.user)
    if redirect_response:
        return redirect_response

    review = get_object_or_404(Review, store=store, pk=pk)
    action = request.POST.get("action", "save").strip()

    try:
        if action == "remove":
            review.remove_reply()
            messages.info(request, "Your reply was removed.")
        else:
            reply_text = request.POST.get("reply_text", "").strip()
            review.add_reply(text=reply_text, by=request.user)
            messages.success(request, "Reply posted to review.")
    except ValidationError as exc:
        messages.error(request, exc.message)

    return redirect("shopkeeper:reviews")

@login_required
def help_support(request):
    if request.method == "POST":
        messages.success(request, "Support ticket submitted.")
        return redirect("shopkeeper:support")
    return render(request, "shopkeeper/communication/support.html", {"page_title": "Help & Support"})