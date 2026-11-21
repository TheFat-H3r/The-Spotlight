from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

from accounts.models import User
from stores.models import Store
from transactions.models import Booking, Order


@staff_member_required
def admin_home(request):
    open_order_statuses = (
        Order.Status.PENDING,
        Order.Status.CONFIRMED,
        Order.Status.PREPARING,
        Order.Status.READY,
    )
    context = {
        "customer_count": User.objects.filter(role=User.Role.CUSTOMER).count(),
        "active_store_count": Store.objects.filter(
            status=Store.Status.ACTIVE
        ).count(),
        "pending_order_count": Order.objects.filter(
            status=Order.Status.PENDING
        ).count(),
        "open_order_count": Order.objects.filter(
            status__in=open_order_statuses
        ).count(),
        "pending_booking_count": Booking.objects.filter(
            status=Booking.Status.PENDING
        ).count(),
        "recent_orders": (
            Order.objects.select_related("customer", "store")
            .order_by("-created_at")
        ),
        "recent_bookings": (
            Booking.objects.select_related(
                "customer", "service", "service__store"
            )
            .order_by("-created_at")
        ),
    }
    return render(request, "operations/admin_home.html", context)

@staff_member_required
def _placeholder_view(request, title, description, nav_key):
    return render(
        request,
        "operations/placeholder.html",
        {
            "page_title": title,
            "page_description": description,
            "active_nav": nav_key,
        },
    )


@staff_member_required
def authorize_stores(request):
    return _placeholder_view(
        request,
        "Authorize stores",
        "Review and approve pending vendor store applications.",
        "authorize_stores",
    )


@staff_member_required
def authorize_ads(request):
    return _placeholder_view(
        request,
        "Ads & announcements",
        "Moderate promoted listings, banners, and store announcements.",
        "authorize_ads",
    )


@staff_member_required
def complaints_list(request):
    return _placeholder_view(
        request,
        "Complaints & disputes",
        "Investigate and resolve customer or vendor escalations.",
        "complaints",
    )


@staff_member_required
def manage_stores(request):
    return _placeholder_view(
        request,
        "Manage stores",
        "Directory of all active, suspended, and archived marketplace stores.",
        "stores",
    )


@staff_member_required
def manage_categories(request):
    return _placeholder_view(
        request,
        "Categories",
        "Create and organize product and service taxonomy.",
        "categories",
    )


@staff_member_required
def manage_catalog(request):
    return _placeholder_view(
        request,
        "Products & services",
        "Audit marketplace product listings and service offerings.",
        "catalog",
    )


@staff_member_required
def manage_users(request):
    return _placeholder_view(
        request,
        "Manage users",
        "Manage customer accounts, vendor owners, and staff permissions.",
        "users",
    )

@staff_member_required
def manage_orders(request):
    return _placeholder_view(
        request,
        "Orders",
        "View and manage all customer orders across the marketplace.",
        "orders",
    )

@staff_member_required
def manage_bookings(request):
    return _placeholder_view(
        request,
        "Bookings",
        "View and manage all customer bookings across the marketplace.",
        "bookings",
    )


@staff_member_required
def manage_payouts(request):
    return _placeholder_view(
        request,
        "Payouts & commissions",
        "Track vendor disbursements and platform commission fees.",
        "payouts",
    )


@staff_member_required
def notifications_center(request):
    return _placeholder_view(
        request,
        "Notifications",
        "Send broadcast alerts and view system notification logs.",
        "notifications",
    )


@staff_member_required
def manage_reviews(request):
    return _placeholder_view(
        request,
        "Reviews & ratings",
        "Moderate customer feedback and flagged reviews.",
        "reviews",
    )

@staff_member_required
def admin_settings(request):
    return _placeholder_view(
        request,
        "Settings",
        "Configure platform settings, integrations, and system preferences.",
        "settings",
    )