from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from accounts.models import User
from marketing.models import Advertisement, Announcement
from operations.models import CommissionPlan, Complaint, Payout, StoreSubscription
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
def marketing(request):
    if request.method == "POST":
        item_type = request.POST.get("item_type")  # "ad" or "announcement"
        action = request.POST.get("action")

        if item_type == "ad":
            ad = get_object_or_404(Advertisement, pk=request.POST.get("item_id"))

            if action == "approve":
                ad.status = Advertisement.Status.ACTIVE
                ad.is_active = True
                ad.save(update_fields=["status", "is_active", "updated_at"])
                messages.success(request, f"Approved ad: '{ad.title}'.")

            elif action == "reject":
                ad.status = Advertisement.Status.REJECTED
                ad.is_active = False
                ad.save(update_fields=["status", "is_active", "updated_at"])
                messages.warning(request, f"Rejected ad: '{ad.title}'.")

            elif action == "toggle":
                if ad.status == Advertisement.Status.ACTIVE:
                    ad.status = Advertisement.Status.PAUSED
                    ad.is_active = False
                    messages.info(request, f"Paused ad: '{ad.title}'.")
                else:
                    ad.status = Advertisement.Status.ACTIVE
                    ad.is_active = True
                    messages.success(request, f"Activated ad: '{ad.title}'.")
                ad.save(update_fields=["status", "is_active", "updated_at"])

            elif action == "delete":
                title = ad.title
                ad.delete()
                messages.warning(request, f"Deleted ad: '{title}'.")

        elif item_type == "announcement":
            announcement = get_object_or_404(Announcement, pk=request.POST.get("item_id"))

            if action in ("approve", "toggle"):
                announcement.is_active = not announcement.is_active
                announcement.save(update_fields=["is_active", "updated_at"])
                state = "Published" if announcement.is_active else "Unpublished"
                messages.success(request, f"{state} announcement: '{announcement.title}'.")

            elif action == "delete":
                title = announcement.title
                announcement.delete()
                messages.warning(request, f"Deleted announcement: '{title}'.")

        return redirect("operations:marketing")

    pending_ads = (
        Advertisement.objects.filter(status=Advertisement.Status.PENDING)
        .select_related("store", "user")
        .order_by("created_at")
    )
    current_ads = (
        Advertisement.objects.exclude(status=Advertisement.Status.PENDING)
        .select_related("store", "user")
        .order_by("-created_at")
    )
    pending_announcements = (
        Announcement.objects.filter(is_active=False)
        .select_related("store", "user")
        .order_by("created_at")
    )
    current_announcements = (
        Announcement.objects.filter(is_active=True)
        .select_related("store", "user")
        .order_by("-created_at")
    )

    return render(
        request,
        "operations/marketing.html",
        {
            "pending_ads": pending_ads,
            "current_ads": current_ads,
            "pending_announcements": pending_announcements,
            "current_announcements": current_announcements,
            "pending_ad_count": pending_ads.count(),
            "pending_announcement_count": pending_announcements.count(),
        },
    )


@staff_member_required
def marketing_ad_form(request, pk=None):
    ad = get_object_or_404(Advertisement, pk=pk) if pk else None
    stores = Store.objects.filter(status=Store.Status.ACTIVE).order_by("name")

    if request.method == "POST":
        store_id = request.POST.get("store")
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        target_url = request.POST.get("target_url", "").strip()
        start_date = request.POST.get("start_date")
        end_date = request.POST.get("end_date")
        budget = request.POST.get("budget") or "0.00"
        status = request.POST.get("status", Advertisement.Status.ACTIVE)
        is_active = request.POST.get("is_active") == "on"
        banner_image = request.FILES.get("banner_image")

        if not (store_id and title and start_date and end_date):
            messages.error(request, "Store, title, start date, and end date are required.")
        else:
            store = get_object_or_404(Store, pk=store_id)
            if ad is None:
                ad = Advertisement(user=request.user)

            ad.store = store
            ad.title = title
            ad.description = description
            ad.target_url = target_url
            ad.start_date = start_date
            ad.end_date = end_date
            ad.budget = budget
            ad.status = status
            ad.is_active = is_active
            if banner_image:
                ad.banner_image = banner_image

            ad.save()
            messages.success(request, f"Advertisement '{ad.title}' saved.")
            return redirect("operations:marketing")

    return render(
        request,
        "operations/marketing_ad_form.html",
        {
            "ad": ad,
            "stores": stores,
            "statuses": Advertisement.Status.choices,
        },
    )


@staff_member_required
def marketing_announcement_form(request, pk=None):
    announcement = get_object_or_404(Announcement, pk=pk) if pk else None
    stores = Store.objects.filter(status=Store.Status.ACTIVE).order_by("name")

    if request.method == "POST":
        store_id = request.POST.get("store") or None
        title = request.POST.get("title", "").strip()
        content = request.POST.get("content", "").strip()
        start_date = request.POST.get("start_date") or None
        end_date = request.POST.get("end_date") or None
        is_active = request.POST.get("is_active") == "on"
        banner_image = request.FILES.get("banner_image")

        if not (title and content):
            messages.error(request, "Title and content are required.")
        else:
            store = get_object_or_404(Store, pk=store_id) if store_id else None
            if announcement is None:
                announcement = Announcement(user=request.user)

            announcement.store = store
            announcement.title = title
            announcement.content = content
            announcement.start_date = start_date
            announcement.end_date = end_date
            announcement.is_active = is_active
            if banner_image:
                announcement.banner_image = banner_image

            announcement.save()
            messages.success(request, f"Announcement '{announcement.title}' saved.")
            return redirect("operations:marketing")

    return render(
        request,
        "operations/marketing_announcement_form.html",
        {
            "announcement": announcement,
            "stores": stores,
        },
    )

@staff_member_required
def complaints(request):
    if request.method == "POST":
        complaint = get_object_or_404(Complaint, pk=request.POST.get("complaint_id"))
        action = request.POST.get("action")

        if action == "investigate":
            complaint.status = Complaint.Status.IN_PROGRESS
            if not complaint.assigned_to:
                complaint.assigned_to = request.user
            complaint.save(update_fields=["status", "assigned_to", "updated_at"])
            messages.info(request, f"{complaint.reference} marked as Under Investigation.")

        elif action == "assign_me":
            complaint.assigned_to = request.user
            if complaint.status == Complaint.Status.OPEN:
                complaint.status = Complaint.Status.IN_PROGRESS
            complaint.save(update_fields=["assigned_to", "status", "updated_at"])
            messages.success(request, f"{complaint.reference} assigned to you.")

        elif action == "resolve":
            notes = request.POST.get("resolution_notes", "").strip()
            complaint.mark_resolved(admin_user=request.user, notes=notes, dismissed=False)
            messages.success(request, f"{complaint.reference} marked as Resolved.")

        elif action == "dismiss":
            notes = request.POST.get("resolution_notes", "").strip()
            complaint.mark_resolved(admin_user=request.user, notes=notes, dismissed=True)
            messages.warning(request, f"{complaint.reference} has been Dismissed.")

        elif action == "reopen":
            complaint.status = Complaint.Status.OPEN
            complaint.resolved_by = None
            complaint.resolved_at = None
            complaint.save(update_fields=["status", "resolved_by", "resolved_at", "updated_at"])
            messages.info(request, f"{complaint.reference} reopened.")

        elif action == "delete":
            ref = complaint.reference
            complaint.delete()
            messages.warning(request, f"Deleted complaint {ref}.")

        return redirect("operations:complaints")

    base_qs = Complaint.objects.select_related(
        "reporter",
        "assigned_to",
        "store",
        "order",
        "booking",
        "review",
        "resolved_by",
    )

    active_complaints = base_qs.filter(
        status__in=(Complaint.Status.OPEN, Complaint.Status.IN_PROGRESS)
    ).order_by("-created_at")

    closed_complaints = base_qs.filter(
        status__in=(Complaint.Status.RESOLVED, Complaint.Status.DISMISSED)
    ).order_by("-resolved_at", "-updated_at")

    return render(
        request,
        "operations/complaints.html",
        {
            "active_complaints": active_complaints,
            "closed_complaints": closed_complaints,
            "open_count": active_complaints.filter(status=Complaint.Status.OPEN).count(),
            "investigating_count": active_complaints.filter(status=Complaint.Status.IN_PROGRESS).count(),
            "urgent_count": active_complaints.filter(priority=Complaint.Priority.URGENT).count(),
            "resolved_count": closed_complaints.filter(status=Complaint.Status.RESOLVED).count(),
        },
    )


@staff_member_required
def complaint_form(request, pk=None):
    complaint = get_object_or_404(Complaint, pk=pk) if pk else None
    staff_users = User.objects.filter(is_staff=True, is_active=True).order_by("full_name", "email")

    if request.method == "POST":
        category = request.POST.get("category", Complaint.Category.OTHER)
        priority = request.POST.get("priority", Complaint.Priority.MEDIUM)
        status = request.POST.get("status", Complaint.Status.OPEN)
        subject = request.POST.get("subject", "").strip()
        description = request.POST.get("description", "").strip()
        resolution_notes = request.POST.get("resolution_notes", "").strip()
        assigned_to_id = request.POST.get("assigned_to") or None
        evidence = request.FILES.get("evidence")

        if not (subject and description):
            messages.error(request, "Subject and description are required.")
        else:
            if complaint is None:
                complaint = Complaint(reporter=request.user)

            complaint.category = category
            complaint.priority = priority
            complaint.status = status
            complaint.subject = subject
            complaint.description = description
            complaint.resolution_notes = resolution_notes
            complaint.assigned_to_id = assigned_to_id # type: ignore
            if evidence:
                complaint.evidence = evidence

            if status in (Complaint.Status.RESOLVED, Complaint.Status.DISMISSED):
                complaint.mark_resolved(
                    admin_user=request.user,
                    notes=resolution_notes,
                    dismissed=(status == Complaint.Status.DISMISSED),
                )
            else:
                complaint.save()

            messages.success(request, f"Complaint {complaint.reference} saved.")
            return redirect("operations:complaints")

    return render(
        request,
        "operations/complaint_form.html",
        {
            "complaint": complaint,
            "staff_users": staff_users,
            "categories": Complaint.Category.choices,
            "priorities": Complaint.Priority.choices,
            "statuses": Complaint.Status.choices,
        },
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