from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from accounts.models import User
from operations.models import CommissionPlan, Payout, StoreSubscription
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
    if request.method == "POST":
        action = request.POST.get("action")
        store = get_object_or_404(Store.objects.select_related("owner", "business_type"), pk=request.POST.get("store_id"))

        if action == "approve":
            make_featured = request.POST.get("is_featured") == "on"
            grant_trial = request.POST.get("grant_trial") == "on"

            store.status = Store.Status.ACTIVE
            if make_featured:
                store.is_featured = True
            store.save(update_fields=["status", "is_featured", "updated_at"])

            # Automatically attach default CommissionPlan & free trial if not yet subscribed
            if not hasattr(store, "subscription"):
                default_plan = CommissionPlan.objects.filter(is_active=True).first()
                if default_plan:
                    now = timezone.now()
                    trial_days = default_plan.default_trial_days if grant_trial else 0
                    trial_end = now + timedelta(days=trial_days) if trial_days > 0 else None

                    StoreSubscription.objects.create(
                        store=store,
                        plan=default_plan,
                        status=(
                            StoreSubscription.Status.TRIAL
                            if trial_end
                            else StoreSubscription.Status.ACTIVE
                        ),
                        current_period_start=now,
                        current_period_end=now + timedelta(days=30),
                        trial_ends_at=trial_end,
                    )

            messages.success(request, f"'{store.name}' is now Active and visible on The Spotlight.")
            return redirect("operations:authorize-stores")

        if action == "suspend":
            store.status = Store.Status.SUSPENDED
            store.is_featured = False
            store.save(update_fields=["status", "is_featured", "updated_at"])
            messages.warning(request, f"'{store.name}' has been suspended.")
            return redirect("operations:authorize-stores")

        if action == "revert_draft":
            store.status = Store.Status.DRAFT
            store.save(update_fields=["status", "updated_at"])
            messages.info(request, f"'{store.name}' moved back to Draft queue.")
            return redirect("operations:authorize-stores")

    base_qs = (
        Store.objects.select_related("owner", "business_type")
        .prefetch_related("categories")
        .annotate(
            product_count=Count("products", distinct=True),
            service_count=Count("services", distinct=True),
        )
    )

    pending_stores = base_qs.filter(status=Store.Status.DRAFT).order_by("created_at")
    suspended_stores = base_qs.filter(status=Store.Status.SUSPENDED).order_by("-updated_at")
    active_count = Store.objects.filter(status=Store.Status.ACTIVE).count()
    default_plan = CommissionPlan.objects.filter(is_active=True).first()

    return render(
        request,
        "operations/authorize_stores.html",
        {
            "pending_stores": pending_stores,
            "suspended_stores": suspended_stores,
            "pending_count": pending_stores.count(),
            "suspended_count": suspended_stores.count(),
            "active_count": active_count,
            "default_plan": default_plan,
        },
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
    if request.method == "POST":
        action = request.POST.get("action")

        # 1. Generate monthly/period payout for one store or all active stores
        if action == "generate_payout":
            store_id = request.POST.get("store_id")
            start_str = request.POST.get("period_start")
            end_str = request.POST.get("period_end")

            start_date = parse_date(start_str) if start_str else None
            end_date = parse_date(end_str) if end_str else None

            if not start_date or not end_date or end_date < start_date:
                messages.error(request, "Please select a valid date range.")
                return redirect("operations:payouts")

            tz = timezone.get_current_timezone()
            period_start = timezone.make_aware(datetime.combine(start_date, time.min), tz)
            # Inclusive end date -> midnight of the following day
            period_end = timezone.make_aware(datetime.combine(end_date + timedelta(days=1), time.min), tz)

            stores_qs = Store.objects.filter(subscription__isnull=False)
            if store_id and store_id != "all":
                stores_qs = stores_qs.filter(pk=store_id)

            created_count = 0
            for store in stores_qs:
                already_exists = Payout.objects.filter(
                    store=store,
                    period_start=period_start,
                    period_end=period_end,
                ).exists()
                if not already_exists:
                    generate_store_payout(store, period_start, period_end) # type: ignore
                    created_count += 1

            if created_count:
                messages.success(request, f"Generated {created_count} payout statement(s).")
            else:
                messages.warning(request, "No new payouts generated (statements already exist for that period).")
            return redirect("operations:payouts")

        # 2. Mark a payout as Paid
        if action == "mark_paid":
            payout = get_object_or_404(Payout, pk=request.POST.get("payout_id"))
            payout.status = Payout.Status.PAID
            payout.payment_method = request.POST.get("payment_method", "").strip()
            payout.transaction_reference = request.POST.get("transaction_reference", "").strip()
            payout.approved_by = request.user
            payout.paid_at = timezone.now()
            payout.save(
                update_fields=[
                    "status",
                    "payment_method",
                    "transaction_reference",
                    "approved_by",
                    "paid_at",
                    "updated_at",
                ]
            )
            messages.success(request, f"Payout {payout.reference} marked as Paid.")
            return redirect("operations:payouts")

        # 3. Grant or update a store's commission-free grace period
        if action == "grant_grace":
            sub = get_object_or_404(StoreSubscription, pk=request.POST.get("subscription_id"))
            grace_date_str = request.POST.get("grace_period_ends_at")
            grace_reason = request.POST.get("grace_reason", "").strip()

            grace_date = parse_date(grace_date_str) if grace_date_str else None
            if grace_date:
                tz = timezone.get_current_timezone()
                sub.grace_period_ends_at = timezone.make_aware(datetime.combine(grace_date, time.max), tz)
                sub.status = StoreSubscription.Status.GRACE
                sub.grace_reason = grace_reason
                sub.save(update_fields=["grace_period_ends_at", "status", "grace_reason", "updated_at"])
                messages.success(
                    request,
                    f"Granted commission-free grace period to {sub.store.name} until {grace_date:%d %b %Y}.",
                )
            else:
                sub.grace_period_ends_at = None
                sub.grace_reason = ""
                if sub.status == StoreSubscription.Status.GRACE:
                    sub.status = StoreSubscription.Status.ACTIVE
                sub.save(update_fields=["grace_period_ends_at", "status", "grace_reason", "updated_at"])
                messages.info(request, f"Cleared grace period for {sub.store.name}.")
            return redirect("operations:payouts")

    payouts = Payout.objects.select_related("store", "subscription__plan").all()
    subscriptions = StoreSubscription.objects.select_related("store", "plan").order_by("store__name")

    pending_payouts_qs = payouts.filter(status__in=[Payout.Status.DRAFT, Payout.Status.PENDING, Payout.Status.PROCESSING])
    paid_payouts_qs = payouts.filter(status=Payout.Status.PAID)

    total_pending_amount = pending_payouts_qs.aggregate(total=Sum("net_payout"))["total"] or Decimal("0.00")
    total_commission_earned = paid_payouts_qs.aggregate(total=Sum("commission_amount"))["total"] or Decimal("0.00")
    total_exempt_sales = payouts.aggregate(total=Sum("exempt_sales"))["total"] or Decimal("0.00")

    now = timezone.now()
    waived_store_count = sum(1 for sub in subscriptions if sub.is_commission_waived(now))

    # Default date range: previous calendar month
    first_of_this_month = now.date().replace(day=1)
    last_of_prev_month = first_of_this_month - timedelta(days=1)
    first_of_prev_month = last_of_prev_month.replace(day=1)

    return render(
        request,
        "operations/payouts.html",
        {
            "payouts": payouts,
            "subscriptions": subscriptions,
            "pending_payout_count": pending_payouts_qs.count(),
            "total_pending_amount": total_pending_amount,
            "total_commission_earned": total_commission_earned,
            "total_exempt_sales": total_exempt_sales,
            "waived_store_count": waived_store_count,
            "default_period_start": first_of_prev_month.isoformat(),
            "default_period_end": last_of_prev_month.isoformat(),
            "now": now,
        },
    )


@staff_member_required
def payout_detail(request, pk):
    payout = get_object_or_404(
        Payout.objects.select_related("store", "subscription__plan", "approved_by"),
        pk=pk,
    )
    items = payout.items.select_related("order", "booking__service").order_by("-created_at") # type: ignore
    return render(
        request,
        "operations/payout_detail.html",
        {
            "payout": payout,
            "items": items,
        },
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