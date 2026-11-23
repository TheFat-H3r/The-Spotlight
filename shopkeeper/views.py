from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.utils import timezone

from stores.models import Product, Review, Service, Store
from transactions.models import Booking, Order, VendorNotification


ZERO = Decimal("0.00")


@login_required
def home(request):
    """
    Vendor dashboard.

    All figures are scoped to every store owned by the currently logged-in
    vendor. A vendor cannot see another vendor's stores or transactions.
    """
    vendor = request.user

    stores = Store.objects.filter(owner=vendor)
    products = Product.objects.filter(store__owner=vendor)
    services = Service.objects.filter(store__owner=vendor)
    orders = Order.objects.filter(store__owner=vendor)
    bookings = Booking.objects.filter(service__store__owner=vendor)
    reviews = Review.objects.filter(
        store__owner=vendor,
        status=Review.Status.PUBLISHED,
    )
    notifications = VendorNotification.objects.filter(store__owner=vendor)

    # Store and catalogue statistics
    total_stores = stores.count()
    active_stores = stores.filter(status=Store.Status.ACTIVE).count()
    draft_stores = stores.filter(status=Store.Status.DRAFT).count()
    suspended_stores = stores.filter(status=Store.Status.SUSPENDED).count()

    total_products = products.count()
    available_products = products.filter(is_available=True).count()
    low_stock_products = products.filter(
        is_available=True,
        stock__lte=5,
    ).select_related("store").order_by("stock", "name")[:6]

    total_services = services.count()
    available_services = services.filter(is_available=True).count()

    # Order and sales statistics
    completed_orders = orders.filter(status=Order.Status.COMPLETED)
    completed_order_value = (
        completed_orders.aggregate(total=Sum("total"))["total"] or ZERO
    )
    paid_order_value = (
        completed_orders.filter(payment_status=Order.PaymentStatus.PAID)
        .aggregate(total=Sum("total"))["total"]
        or ZERO
    )

    total_orders = orders.count()
    pending_orders = orders.filter(status=Order.Status.PENDING).count()
    processing_orders = orders.filter(
        status__in=[Order.Status.CONFIRMED, Order.Status.PREPARING]
    ).count()
    completed_orders_count = completed_orders.count()

    # Booking statistics
    pending_bookings = bookings.filter(status=Booking.Status.PENDING).count()
    confirmed_bookings = bookings.filter(status=Booking.Status.CONFIRMED).count()
    completed_bookings = bookings.filter(status=Booking.Status.COMPLETED).count()

    # Review statistics. Store.rating_average is already denormalised, but
    # this average is calculated from the vendor's published reviews.
    review_stats = reviews.aggregate(
        average=Avg("overall_rating"),
        count=Count("id"),
    )
    average_rating = review_stats["average"] or ZERO
    total_reviews = review_stats["count"] or 0

    # Notifications
    unread_notifications = notifications.filter(is_read=False).count()
    recent_notifications = notifications.select_related(
        "store", "order"
    ).order_by("-created_at")[:5]

    # Recent activity
    recent_orders = (
        orders.select_related("store", "customer")
        .order_by("-created_at")
    )
    recent_bookings = (
        bookings.select_related("service", "customer", "slot", "service__store")
        .order_by("-created_at")[:6]
    )
    recent_reviews = (
        reviews.select_related("store", "product", "service", "author")
        .order_by("-created_at")[:6]
    )

    # Seven-day completed-order value trend. The chart is generated from
    # completed_at, not order creation time.
    today = timezone.localdate()
    first_day = today - timedelta(days=6)

    daily_rows = (
        completed_orders.filter(
            completed_at__date__gte=first_day,
            completed_at__date__lte=today,
        )
        .annotate(day=TruncDate("completed_at"))
        .values("day")
        .annotate(value=Sum("total"), order_count=Count("id"))
        .order_by("day")
    )
    daily_data = {
        row["day"]: {
            "value": row["value"] or ZERO,
            "order_count": row["order_count"],
        }
        for row in daily_rows
    }

    sales_chart = []
    for offset in range(7):
        day = first_day + timedelta(days=offset)
        day_data = daily_data.get(
            day,
            {"value": ZERO, "order_count": 0},
        )
        sales_chart.append({
            "label": day.strftime("%a"),
            "date": day,
            "value": day_data["value"],
            "order_count": day_data["order_count"],
        })

    chart_max = max((item["value"] for item in sales_chart), default=ZERO)
    for item in sales_chart:
        if chart_max > ZERO:
            item["bar_height"] = max(
                6, int((item["value"] / chart_max) * 100)
            )
        else:
            item["bar_height"] = 6

    context = {
        "stores": stores.order_by("name"),
        "total_stores": total_stores,
        "active_stores": active_stores,
        "draft_stores": draft_stores,
        "suspended_stores": suspended_stores,

        "total_products": total_products,
        "available_products": available_products,
        "total_services": total_services,
        "available_services": available_services,
        "low_stock_products": low_stock_products,

        "total_orders": total_orders,
        "pending_orders": pending_orders,
        "processing_orders": processing_orders,
        "completed_orders_count": completed_orders_count,
        "completed_order_value": completed_order_value,
        "paid_order_value": paid_order_value,

        "pending_bookings": pending_bookings,
        "confirmed_bookings": confirmed_bookings,
        "completed_bookings": completed_bookings,

        "average_rating": average_rating,
        "total_reviews": total_reviews,

        "unread_notifications": unread_notifications,
        "recent_notifications": recent_notifications,
        "recent_orders": recent_orders,
        "recent_bookings": recent_bookings,
        "recent_reviews": recent_reviews,

        "sales_chart": sales_chart,
        "today": today,
    }

    return render(request, "shopkeeper/home.html", context)
