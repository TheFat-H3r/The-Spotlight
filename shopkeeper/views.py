from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import redirect, render
from django.utils import timezone

from stores.models import Product, Review, Service, Store
from transactions.models import Booking, Order, VendorNotification
from .context_processors import _resolve_business_mode


ZERO = Decimal("0.00")


@login_required
def home(request):
    """
    Single-store vendor dashboard adapted dynamically to the store's business type
    (Product business vs. Service business).
    """
    vendor = request.user

    # Prevent pure customer accounts from accessing the vendor dashboard
    if getattr(vendor, "role", None) == "customer" and not vendor.is_staff:
        return redirect("core:home")

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