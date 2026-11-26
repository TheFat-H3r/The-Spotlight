from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import update_session_auth_hash
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.db.models import Q, Avg, Count, ProtectedError, Sum
from django.forms import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from accounts.models import User
from marketing.models import Advertisement, Announcement
from operations.models import AdminNotification, BroadcastAnnouncement, CommissionPlan, Complaint, Payout, PlatformSettings, StoreSubscription
from stores.models import BusinessType, Category, Product, Review, Service, Store, unique_slug
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
def stores_management(request):
    if request.method == "POST":
        store = get_object_or_404(Store, pk=request.POST.get("store_id"))
        action = request.POST.get("action")

        if action == "activate":
            store.status = Store.Status.ACTIVE
            store.save(update_fields=["status", "updated_at"])
            messages.success(request, f"Store '{store.name}' is now Active.")

        elif action == "suspend":
            store.status = Store.Status.SUSPENDED
            store.save(update_fields=["status", "updated_at"])
            messages.warning(request, f"Store '{store.name}' has been Suspended.")

        elif action == "draft":
            store.status = Store.Status.DRAFT
            store.save(update_fields=["status", "updated_at"])
            messages.info(request, f"Store '{store.name}' moved back to Draft.")

        elif action == "toggle_featured":
            store.is_featured = not store.is_featured
            store.save(update_fields=["is_featured", "updated_at"])
            state = "featured" if store.is_featured else "removed from featured"
            messages.info(request, f"Store '{store.name}' {state}.")

        elif action == "delete":
            name = store.name
            store.delete()
            messages.warning(request, f"Deleted store '{name}'.")

        return redirect("operations:stores")

    base_qs = (
        Store.objects.select_related("owner", "business_type")
        .prefetch_related("categories")
        .annotate(
            product_count=Count("products", distinct=True),
            service_count=Count("services", distinct=True),
        )
    )

    draft_stores = base_qs.filter(status=Store.Status.DRAFT).order_by("-created_at")
    managed_stores = base_qs.exclude(status=Store.Status.DRAFT).order_by("-is_featured", "-created_at")

    return render(
        request,
        "operations/stores.html",
        {
            "draft_stores": draft_stores,
            "managed_stores": managed_stores,
            "draft_store_count": draft_stores.count(),
            "active_store_count": managed_stores.filter(status=Store.Status.ACTIVE).count(),
            "featured_store_count": base_qs.filter(is_featured=True).count(),
            "suspended_store_count": managed_stores.filter(status=Store.Status.SUSPENDED).count(),
        },
    )


@staff_member_required
def store_form(request, pk=None):
    store = (
        get_object_or_404(
            Store.objects.select_related("owner", "business_type").prefetch_related("categories"),
            pk=pk,
        )
        if pk
        else None
    )
    owners = User.objects.filter(is_active=True).order_by("full_name", "email")
    business_types = BusinessType.objects.all().order_by("name")
    categories = Category.objects.all().order_by("name")

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        business_type_id = request.POST.get("business_type")
        owner_id = request.POST.get("owner") or (store.owner_id if store else None)

        if not (name and business_type_id and owner_id):
            messages.error(request, "Store name, owner, and business type are required.")
        else:
            if store is None:
                store = Store(owner_id=owner_id)
            else:
                store.owner_id = owner_id

            store.name = name
            store.tagline = request.POST.get("tagline", "").strip()
            store.description = request.POST.get("description", "").strip()
            store.business_type_id = business_type_id
            store.contact_phone = request.POST.get("contact_phone", "").strip()
            store.contact_email = request.POST.get("contact_email", "").strip()
            store.whatsapp = request.POST.get("whatsapp", "").strip()
            store.pickup_location = request.POST.get("pickup_location", "").strip()
            store.status = request.POST.get("status", Store.Status.ACTIVE)
            store.offers_delivery = request.POST.get("offers_delivery") == "on"
            store.is_accepting_orders = request.POST.get("is_accepting_orders") == "on"
            store.is_featured = request.POST.get("is_featured") == "on"

            if request.FILES.get("logo"):
                store.logo = request.FILES["logo"]
            if request.FILES.get("banner"):
                store.banner = request.FILES["banner"]

            store.save()
            store.categories.set(request.POST.getlist("categories"))

            messages.success(request, f"Store '{store.name}' saved.")
            return redirect("operations:stores")

    return render(
        request,
        "operations/store_form.html",
        {
            "store": store,
            "owners": owners,
            "business_types": business_types,
            "categories": categories,
            "selected_category_ids": set(store.categories.values_list("id", flat=True)) if store else set(),
            "statuses": Store.Status.choices,
        },
    )


@staff_member_required
def categories_management(request):
    if request.method == "POST":
        item_type = request.POST.get("item_type")
        action = request.POST.get("action")

        if item_type == "category" and action == "delete":
            category = get_object_or_404(Category, pk=request.POST.get("item_id"))
            name = category.name
            category.delete()
            messages.warning(request, f"Deleted category '{name}'.")

        elif item_type == "business_type" and action == "delete":
            bt = get_object_or_404(BusinessType, pk=request.POST.get("item_id"))
            name = bt.name
            try:
                bt.delete()
                messages.warning(request, f"Deleted business type '{name}'.")
            except ProtectedError:
                messages.error(
                    request,
                    f"Cannot delete '{name}' because one or more stores are still assigned to it.",
                )

        return redirect("operations:categories")

    categories = Category.objects.annotate(store_count=Count("stores")).order_by("name")
    business_types = BusinessType.objects.annotate(store_count=Count("stores")).order_by("name")

    return render(
        request,
        "operations/categories.html",
        {
            "categories": categories,
            "business_types": business_types,
            "category_count": categories.count(),
            "business_type_count": business_types.count(),
        },
    )


@staff_member_required
def category_form(request, pk=None):
    category = get_object_or_404(Category, pk=pk) if pk else None

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        slug = request.POST.get("slug", "").strip()

        if not name:
            messages.error(request, "Category name is required.")
        else:
            try:
                if category is None:
                    category = Category(name=name, slug=slug)
                else:
                    category.name = name
                    category.slug = slug  # blank triggers auto-generation if cleared, or keeps custom slug
                category.save()
                messages.success(request, f"Category '{category.name}' saved.")
                return redirect("operations:categories")
            except IntegrityError:
                messages.error(request, "A category with this name or slug already exists.")

    return render(
        request,
        "operations/category_form.html",
        {"category": category},
    )


@staff_member_required
def business_type_form(request, pk=None):
    business_type = get_object_or_404(BusinessType, pk=pk) if pk else None

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        store_type = request.POST.get("store_type", BusinessType.StoreType.PRODUCTS)

        if not name:
            messages.error(request, "Business type name is required.")
        else:
            try:
                if business_type is None:
                    business_type = BusinessType(name=name, store_type=store_type)
                else:
                    business_type.name = name
                    business_type.store_type = store_type
                business_type.save()
                messages.success(request, f"Business type '{business_type.name}' saved.")
                return redirect("operations:categories")
            except IntegrityError:
                messages.error(request, "A business type with this name already exists.")

    return render(
        request,
        "operations/business_type_form.html",
        {
            "business_type": business_type,
            "store_types": BusinessType.StoreType.choices,
        },
    )

@staff_member_required
def catalog_management(request):
    if request.method == "POST":
        item_type = request.POST.get("item_type")
        action = request.POST.get("action")

        if item_type == "product":
            item = get_object_or_404(Product, pk=request.POST.get("item_id"))
        elif item_type == "service":
            item = get_object_or_404(Service, pk=request.POST.get("item_id"))
        else:
            return redirect("operations:catalog")

        if action == "toggle_available":
            item.is_available = not item.is_available
            item.save(update_fields=["is_available", "updated_at"])
            state = "available" if item.is_available else "unavailable"
            messages.success(request, f"'{item.name}' marked as {state}.")

        elif action == "toggle_featured":
            item.is_featured = not item.is_featured
            item.save(update_fields=["is_featured", "updated_at"])
            state = "featured" if item.is_featured else "removed from featured"
            messages.info(request, f"'{item.name}' {state}.")

        elif action == "delete":
            name = item.name
            item.delete()
            messages.warning(request, f"Deleted '{name}'.")

        return redirect("operations:catalog")

    products = Product.objects.select_related("store", "category").order_by("-is_featured", "-created_at")
    services = Service.objects.select_related("store", "category").order_by("-is_featured", "-created_at")

    return render(
        request,
        "operations/catalog.html",
        {
            "products": products,
            "services": services,
            "product_count": products.count(),
            "service_count": services.count(),
            "featured_count": products.filter(is_featured=True).count() + services.filter(is_featured=True).count(),
            "out_of_stock_count": products.filter(stock=0).count(),
        },
    )


@staff_member_required
def product_form(request, pk=None):
    product = get_object_or_404(Product.objects.select_related("store", "category"), pk=pk) if pk else None
    stores = Store.objects.filter(
        store_type__in=(Store.StoreType.PRODUCTS, Store.StoreType.BOTH)
    ).order_by("name")
    categories = Category.objects.all().order_by("name")

    if request.method == "POST":
        store_id = request.POST.get("store")
        name = request.POST.get("name", "").strip()
        slug = request.POST.get("slug", "").strip()
        description = request.POST.get("description", "").strip()
        category_id = request.POST.get("category") or None
        raw_price = request.POST.get("price", "0").strip() or "0"
        raw_stock = request.POST.get("stock", "0").strip() or "0"
        is_available = request.POST.get("is_available") == "on"
        is_featured = request.POST.get("is_featured") == "on"

        try:
            price = Decimal(raw_price)
            stock = max(0, int(raw_stock))
        except (InvalidOperation, ValueError):
            messages.error(request, "Please enter a valid price and stock quantity.")
            price = None
            stock = 0

        if not (store_id and name) or price is None:
            if not (store_id and name):
                messages.error(request, "Store and product name are required.")
        else:
            try:
                if product is None:
                    product = Product()

                product.store_id = store_id
                product.name = name
                product.slug = slug or unique_slug(Product, name, product, max_length=255)
                product.description = description
                product.category_id = category_id
                product.price = price
                product.stock = stock
                product.is_available = is_available
                product.is_featured = is_featured

                if request.FILES.get("image"):
                    product.image = request.FILES["image"]

                product.save()
                messages.success(request, f"Product '{product.name}' saved.")
                return redirect("operations:catalog")
            except IntegrityError:
                messages.error(request, "A product with this slug already exists.")

    return render(
        request,
        "operations/product_form.html",
        {
            "product": product,
            "stores": stores,
            "categories": categories,
        },
    )


@staff_member_required
def service_form(request, pk=None):
    service = get_object_or_404(Service.objects.select_related("store", "category"), pk=pk) if pk else None
    stores = Store.objects.filter(
        store_type__in=(Store.StoreType.SERVICES, Store.StoreType.BOTH)
    ).order_by("name")
    categories = Category.objects.all().order_by("name")

    if request.method == "POST":
        store_id = request.POST.get("store")
        name = request.POST.get("name", "").strip()
        slug = request.POST.get("slug", "").strip()
        description = request.POST.get("description", "").strip()
        category_id = request.POST.get("category") or None
        raw_price = request.POST.get("starting_price", "0").strip() or "0"
        is_available = request.POST.get("is_available") == "on"
        is_featured = request.POST.get("is_featured") == "on"

        try:
            starting_price = Decimal(raw_price)
        except InvalidOperation:
            messages.error(request, "Please enter a valid starting price.")
            starting_price = None

        if not (store_id and name) or starting_price is None:
            if not (store_id and name):
                messages.error(request, "Store and service name are required.")
        else:
            try:
                if service is None:
                    service = Service()

                service.store_id = store_id
                service.name = name
                service.slug = slug or unique_slug(Service, name, service, max_length=265)
                service.description = description
                service.category_id = category_id
                service.starting_price = starting_price
                service.is_available = is_available
                service.is_featured = is_featured

                if request.FILES.get("image"):
                    service.image = request.FILES["image"]

                service.save()
                messages.success(request, f"Service '{service.name}' saved.")
                return redirect("operations:catalog")
            except IntegrityError:
                messages.error(request, "A service with this slug already exists.")

    return render(
        request,
        "operations/service_form.html",
        {
            "service": service,
            "stores": stores,
            "categories": categories,
        },
    )

@staff_member_required
def users_management(request):
    if request.method == "POST":
        target = get_object_or_404(User, pk=request.POST.get("user_id"))
        action = request.POST.get("action")

        if action == "set_role":
            new_role = request.POST.get("role")
            if new_role in dict(User.Role.choices):
                if target.pk == request.user.pk and new_role != User.Role.ADMIN:
                    messages.error(request, "You cannot remove your own Administrator role.")
                else:
                    target.role = new_role
                    update_fields = ["role", "updated_at"]
                    if new_role == User.Role.ADMIN and not target.is_staff:
                        target.is_staff = True
                        update_fields.append("is_staff")
                    target.save(update_fields=update_fields)
                    messages.success(request, f"Updated {target.full_name} to {target.get_role_display()}.") # type: ignore

        elif action == "toggle_active":
            if target.pk == request.user.pk:
                messages.error(request, "You cannot deactivate your own account.")
            else:
                target.is_active = not target.is_active
                target.save(update_fields=["is_active", "updated_at"])
                state = "activated" if target.is_active else "suspended"
                messages.success(request, f"Account for {target.full_name} {state}.")

        elif action == "verify_email":
            if not target.is_email_verified:
                target.is_email_verified = True
                target.save(update_fields=["is_email_verified", "updated_at"])
                messages.success(request, f"Marked {target.email} as email verified.")

        elif action == "delete":
            if target.pk == request.user.pk:
                messages.error(request, "You cannot delete your own account.")
            else:
                label = f"{target.full_name} ({target.email})"
                target.delete()
                messages.warning(request, f"Deleted user {label}.")

        return redirect("operations:users")

    users_qs = User.objects.annotate(store_count=Count("stores", distinct=True)).order_by("-date_joined")

    return render(
        request,
        "operations/users.html",
        {
            "users": users_qs,
            "total_user_count": users_qs.count(),
            "customer_count": users_qs.filter(role=User.Role.CUSTOMER).count(),
            "vendor_count": users_qs.filter(role=User.Role.VENDOR).count(),
            "admin_count": users_qs.filter(role=User.Role.ADMIN).count(),
            "roles": User.Role.choices,
        },
    )


@staff_member_required
def user_form(request, pk=None):
    target = get_object_or_404(User, pk=pk) if pk else None

    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        full_name = request.POST.get("full_name", "").strip()
        phone = request.POST.get("phone", "").strip()
        student_id = request.POST.get("student_id", "").strip()
        role = request.POST.get("role", User.Role.CUSTOMER)
        course = request.POST.get("course", "").strip()
        cohort = request.POST.get("cohort", "").strip().upper()
        residence = request.POST.get("residence", "").strip()
        room_number = request.POST.get("room_number", "").strip().upper()
        password = request.POST.get("password", "")

        is_active = request.POST.get("is_active") == "on"
        is_staff = request.POST.get("is_staff") == "on"
        is_email_verified = request.POST.get("is_email_verified") == "on"

        if not (email and full_name):
            messages.error(request, "Email and full name are required.")
        elif target is None and not password:
            messages.error(request, "A password is required when creating a new user.")
        elif target and target.pk == request.user.pk and (not is_active or role != User.Role.ADMIN):
            messages.error(request, "You cannot deactivate your own account or demote your own Admin role.")
        else:
            is_new = target is None
            if is_new:
                target = User(email=email)
            else:
                target.email = email

            target.full_name = full_name
            target.phone = phone
            target.student_id = student_id
            target.role = role
            target.course = course
            target.cohort = cohort
            target.residence = residence
            target.room_number = room_number
            target.is_active = is_active
            target.is_staff = True if role == User.Role.ADMIN else is_staff
            target.is_email_verified = is_email_verified

            if password:
                target.set_password(password)

            if request.FILES.get("avatar"):
                target.avatar = request.FILES["avatar"]

            try:
                target.full_clean(exclude=["password"] if not password else None)
                target.save()
                messages.success(request, f"User '{target.full_name}' saved.")
                return redirect("operations:users")
            except ValidationError as exc:
                for field, errs in exc.message_dict.items():
                    for err in errs:
                        messages.error(request, f"{field.replace('_', ' ').title()}: {err}")
            except IntegrityError:
                messages.error(request, "A user with this email already exists.")

    return render(
        request,
        "operations/user_form.html",
        {
            "target_user": target,
            "roles": User.Role.choices,
            "courses": User.Course.choices,
            "residences": User.Residence.choices,
        },
    )

@staff_member_required
def manage_orders(request):
    if request.method == "POST":
        action = request.POST.get("action")
        order = get_object_or_404(Order, pk=request.POST.get("order_id"))
        next_url = request.POST.get("next") or "operations:orders"

        if action == "change_status":
            new_status = request.POST.get("new_status", "").strip()
            note = request.POST.get("note", "").strip()
            try:
                order.change_status(new_status, by=request.user, note=note)
                messages.success(
                    request,
                    f"Order {order.order_number} updated to {order.get_status_display()}.",
                )
            except ValidationError as exc:
                messages.error(request, exc.message)
            return redirect(next_url)

        if action == "update_payment":
            payment_status = request.POST.get("payment_status", "").strip()
            payment_reference = request.POST.get("payment_reference", "").strip()
            if payment_status in dict(Order.PaymentStatus.choices):
                order.payment_status = payment_status
                order.payment_reference = payment_reference
                order.save(update_fields=["payment_status", "payment_reference", "updated_at"])
                messages.success(
                    request,
                    f"Payment status for {order.order_number} updated to {order.get_payment_status_display()}.", # type: ignore
                )
            else:
                messages.error(request, "Invalid payment status selected.")
            return redirect(next_url)

    status_filter = request.GET.get("status", "").strip()
    orders_qs = Order.objects.select_related("store", "customer").prefetch_related("items")

    if status_filter and status_filter in dict(Order.Status.choices):
        orders = orders_qs.filter(status=status_filter)
    else:
        orders = orders_qs.all()

    open_statuses = [
        Order.Status.PENDING,
        Order.Status.CONFIRMED,
        Order.Status.PREPARING,
        Order.Status.READY,
    ]
    open_orders_count = orders_qs.filter(status__in=open_statuses).count()
    completed_orders_qs = orders_qs.filter(status=Order.Status.COMPLETED)
    completed_revenue = completed_orders_qs.aggregate(total=Sum("total"))["total"] or Decimal("0.00")
    unpaid_active_count = orders_qs.filter(
        status__in=open_statuses,
        payment_status=Order.PaymentStatus.UNPAID,
    ).count()

    return render(
        request,
        "operations/orders.html",
        {
            "orders": orders,
            "status_filter": status_filter,
            "status_choices": Order.Status.choices,
            "payment_status_choices": Order.PaymentStatus.choices,
            "total_orders_count": orders_qs.count(),
            "open_orders_count": open_orders_count,
            "completed_orders_count": completed_orders_qs.count(),
            "completed_revenue": completed_revenue,
            "unpaid_active_count": unpaid_active_count,
        },
    )


@staff_member_required
def order_detail(request, pk):
    order = get_object_or_404(
        Order.objects.select_related("store", "customer").prefetch_related(
            "items__product",
            "status_history__changed_by",
        ),
        pk=pk,
    )
    status_label_map = dict(Order.Status.choices)
    allowed_transitions = [
        (code, status_label_map.get(code, code))
        for code in order.allowed_next_statuses()
    ]

    return render(
        request,
        "operations/order_detail.html",
        {
            "order": order,
            "items": order.items.all(),
            "history": order.status_history.all(),
            "allowed_transitions": allowed_transitions,
            "payment_status_choices": Order.PaymentStatus.choices,
        },
    )


@staff_member_required
def manage_bookings(request):
    if request.method == "POST":
        action = request.POST.get("action")
        booking = get_object_or_404(
            Booking.objects.select_related("service__store", "slot", "customer"),
            pk=request.POST.get("booking_id"),
        )
        next_url = request.POST.get("next") or "operations:bookings"
        note_or_reason = request.POST.get("note", "").strip()

        try:
            if action == "approve":
                booking.approve(note=note_or_reason)
                messages.success(request, f"Booking {booking.reference} confirmed.")
            elif action == "reject":
                booking.reject(reason=note_or_reason)
                messages.warning(request, f"Booking {booking.reference} rejected.")
            elif action == "cancel_vendor":
                booking.cancel_by_vendor(reason=note_or_reason)
                messages.warning(request, f"Booking {booking.reference} cancelled.")
            elif action == "complete":
                booking.complete()
                messages.success(request, f"Booking {booking.reference} marked as completed.")
            elif action == "no_show":
                booking.mark_no_show()
                messages.warning(request, f"Booking {booking.reference} marked as no-show.")
            elif action == "update_note":
                booking.vendor_note = note_or_reason
                booking.save(update_fields=["vendor_note", "updated_at"])
                messages.success(request, f"Updated note on booking {booking.reference}.")
            else:
                messages.error(request, "Unknown booking action.")
        except ValidationError as exc:
            messages.error(request, exc.message)

        return redirect(next_url)

    status_filter = request.GET.get("status", "").strip()
    bookings_qs = Booking.objects.select_related(
        "service__store",
        "slot",
        "customer",
    )

    if status_filter and status_filter in dict(Booking.Status.choices):
        bookings = bookings_qs.filter(status=status_filter)
    else:
        bookings = bookings_qs.all()

    now = timezone.now()
    active_bookings_count = bookings_qs.filter(
        status__in=[Booking.Status.PENDING, Booking.Status.CONFIRMED]
    ).count()
    upcoming_confirmed_count = bookings_qs.filter(
        status=Booking.Status.CONFIRMED,
        slot__start_at__gte=now,
    ).count()
    completed_qs = bookings_qs.filter(status=Booking.Status.COMPLETED)
    completed_revenue = completed_qs.aggregate(total=Sum("total_price"))["total"] or Decimal("0.00")

    return render(
        request,
        "operations/bookings.html",
        {
            "bookings": bookings,
            "status_filter": status_filter,
            "status_choices": Booking.Status.choices,
            "total_bookings_count": bookings_qs.count(),
            "active_bookings_count": active_bookings_count,
            "upcoming_confirmed_count": upcoming_confirmed_count,
            "completed_bookings_count": completed_qs.count(),
            "completed_revenue": completed_revenue,
            "now": now,
        },
    )


@staff_member_required
def booking_detail(request, pk):
    booking = get_object_or_404(
        Booking.objects.select_related("service__store", "slot", "customer"),
        pk=pk,
    )
    now = timezone.now()
    has_started = booking.slot.start_at <= now

    return render(
        request,
        "operations/booking_detail.html",
        {
            "booking": booking,
            "has_started": has_started,
            "now": now,
        },
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
def notifications_management(request):
    visible_alerts = AdminNotification.objects.select_related("recipient", "read_by").filter(
        Q(recipient__isnull=True) | Q(recipient=request.user)
    )

    if request.method == "POST":
        item_type = request.POST.get("item_type")
        action = request.POST.get("action")

        # 1. Incoming AdminNotification actions
        if item_type == "notification":
            if action == "mark_all_read":
                unread_qs = visible_alerts.filter(is_read=False)
                count = unread_qs.update(
                    is_read=True,
                    read_at=timezone.now(),
                    read_by=request.user,
                )
                messages.success(request, f"Marked {count} notification(s) as read.")
            else:
                notif = get_object_or_404(visible_alerts, pk=request.POST.get("item_id"))
                if action == "mark_read":
                    notif.mark_as_read(user=request.user)
                    messages.success(request, f"Marked '{notif.title}' as read.")
                elif action == "delete":
                    title = notif.title
                    notif.delete()
                    messages.warning(request, f"Deleted alert '{title}'.")

        # 2. Outgoing BroadcastAnnouncement actions
        elif item_type == "broadcast":
            broadcast = get_object_or_404(BroadcastAnnouncement, pk=request.POST.get("item_id"))
            if action == "toggle_pin":
                broadcast.is_pinned = not broadcast.is_pinned
                broadcast.save(update_fields=["is_pinned"])
                state = "pinned" if broadcast.is_pinned else "unpinned"
                messages.info(request, f"Broadcast '{broadcast.title}' {state}.")
            elif action == "delete":
                title = broadcast.title
                broadcast.delete()
                messages.warning(request, f"Deleted broadcast '{title}'.")

        return redirect("operations:notifications")

    unread_alerts = visible_alerts.filter(is_read=False).order_by("-created_at")
    read_alerts = visible_alerts.filter(is_read=True).order_by("-read_at", "-created_at")[:50]
    broadcasts = BroadcastAnnouncement.objects.select_related("sent_by").order_by("-is_pinned", "-published_at")

    now = timezone.now()
    active_broadcast_count = broadcasts.filter(published_at__lte=now).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    ).count()

    return render(
        request,
        "operations/notifications.html",
        {
            "unread_alerts": unread_alerts,
            "read_alerts": read_alerts,
            "broadcasts": broadcasts,
            "unread_count": unread_alerts.count(),
            "urgent_count": unread_alerts.filter(
                level__in=(AdminNotification.Level.WARNING, AdminNotification.Level.DANGER)
            ).count(),
            "active_broadcast_count": active_broadcast_count,
            "pinned_broadcast_count": broadcasts.filter(is_pinned=True).count(),
        },
    )


@staff_member_required
def broadcast_form(request, pk=None):
    broadcast = get_object_or_404(BroadcastAnnouncement, pk=pk) if pk else None

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        body = request.POST.get("body", "").strip()
        audience = request.POST.get("audience", BroadcastAnnouncement.Audience.ALL)
        is_pinned = request.POST.get("is_pinned") == "on"
        send_email = request.POST.get("send_email") == "on"

        raw_published = request.POST.get("published_at", "").strip()
        raw_expires = request.POST.get("expires_at", "").strip()

        published_at = parse_datetime(raw_published) if raw_published else timezone.now()
        if published_at and timezone.is_naive(published_at):
            published_at = timezone.make_aware(published_at)

        expires_at = parse_datetime(raw_expires) if raw_expires else None
        if expires_at and timezone.is_naive(expires_at):
            expires_at = timezone.make_aware(expires_at)

        if not (title and body):
            messages.error(request, "Title and announcement message are required.")
        elif expires_at and published_at and expires_at <= published_at:
            messages.error(request, "Expiry time must be after the publish time.")
        else:
            is_new = broadcast is None
            if is_new:
                broadcast = BroadcastAnnouncement(sent_by=request.user)

            broadcast.title = title
            broadcast.body = body
            broadcast.audience = audience
            broadcast.is_pinned = is_pinned
            broadcast.send_email = send_email
            broadcast.published_at = published_at or timezone.now()
            broadcast.expires_at = expires_at
            broadcast.save()

            messages.success(request, f"Broadcast '{broadcast.title}' saved.")
            return redirect("operations:notifications")

    return render(
        request,
        "operations/broadcast_form.html",
        {
            "broadcast": broadcast,
            "audiences": BroadcastAnnouncement.Audience.choices,
            "default_published": timezone.localtime(
                broadcast.published_at if broadcast else timezone.now()
            ).strftime("%Y-%m-%dT%H:%M"),
            "default_expires": timezone.localtime(broadcast.expires_at).strftime("%Y-%m-%dT%H:%M")
            if broadcast and broadcast.expires_at
            else "",
        },
    )


@staff_member_required
def admin_notification_create(request):
    staff_users = User.objects.filter(is_staff=True, is_active=True).order_by("full_name", "email")

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        message = request.POST.get("message", "").strip()
        category = request.POST.get("category", AdminNotification.Category.SYSTEM)
        level = request.POST.get("level", AdminNotification.Level.INFO)
        action_url = request.POST.get("action_url", "").strip()
        recipient_id = request.POST.get("recipient") or None

        if not title:
            messages.error(request, "Notification title is required.")
        else:
            AdminNotification.objects.create(
                recipient_id=recipient_id,
                category=category,
                level=level,
                title=title,
                message=message,
                action_url=action_url,
            )
            messages.success(request, f"Internal alert '{title}' posted.")
            return redirect("operations:notifications")

    return render(
        request,
        "operations/notification_form.html",
        {
            "staff_users": staff_users,
            "categories": AdminNotification.Category.choices,
            "levels": AdminNotification.Level.choices,
        },
    )


@staff_member_required
def reviews_management(request):
    if request.method == "POST":
        review = get_object_or_404(Review, pk=request.POST.get("review_id"))
        action = request.POST.get("action")

        if action == "hide":
            if review.status != Review.Status.HIDDEN:
                review.status = Review.Status.HIDDEN
                review.save(update_fields=["status", "updated_at"])
                messages.warning(request, "Review hidden from public storefront and ratings updated.")

        elif action == "publish":
            if review.status != Review.Status.PUBLISHED:
                review.status = Review.Status.PUBLISHED
                review.save(update_fields=["status", "updated_at"])
                messages.success(request, "Review restored to Published and ratings updated.")

        elif action == "remove_reply":
            if review.has_reply:
                review.remove_reply()
                messages.info(request, "Vendor reply removed from review.")

        elif action == "delete":
            review.delete()
            messages.warning(request, "Review permanently deleted and ratings recalculated.")

        return redirect("operations:reviews")

    reviews_qs = (
        Review.objects.select_related(
            "store",
            "product",
            "service",
            "author",
            "replied_by",
            "order_item__order",
            "booking",
        )
        .order_by("-created_at")
    )

    published_qs = reviews_qs.filter(status=Review.Status.PUBLISHED)
    avg_rating = published_qs.aggregate(avg=Avg("overall_rating"))["avg"]

    return render(
        request,    
        "operations/reviews.html",
        {
            "reviews": reviews_qs,
            "total_review_count": reviews_qs.count(),
            "published_count": published_qs.count(),
            "hidden_count": reviews_qs.filter(status=Review.Status.HIDDEN).count(),
            "low_rating_count": published_qs.filter(overall_rating__lte=2).count(),
            "average_rating": round(avg_rating, 2) if avg_rating is not None else "0.00",
        },
    )

@staff_member_required
def admin_settings(request):
    user = request.user
    platform_settings = PlatformSettings.get_solo()

    if request.method == "POST":
        form_type = request.POST.get("form_type")

        # 1. Admin Profile Update
        if form_type == "profile":
            full_name = request.POST.get("full_name", "").strip()
            phone = request.POST.get("phone", "").strip()
            student_id = request.POST.get("student_id", "").strip()
            course = request.POST.get("course", "").strip()
            cohort = request.POST.get("cohort", "").strip().upper()
            residence = request.POST.get("residence", "").strip()
            room_number = request.POST.get("room_number", "").strip().upper()

            if not full_name:
                messages.error(request, "Full name is required.")
            else:
                user.full_name = full_name
                user.phone = phone
                user.student_id = student_id
                user.course = course
                user.cohort = cohort
                user.residence = residence
                user.room_number = room_number

                if request.FILES.get("avatar"):
                    user.avatar = request.FILES["avatar"]

                try:
                    user.full_clean(exclude=["password"])
                    user.save()
                    messages.success(request, "Admin profile updated.")
                    return redirect("operations:admin-settings")
                except ValidationError as exc:
                    for field, errs in exc.message_dict.items():
                        for err in errs:
                            messages.error(request, f"{field.replace('_', ' ').title()}: {err}")

        # 2. Password Update (Email & password accounts only)
        elif form_type == "password":
            if user.auth_provider != User.AuthProvider.EMAIL:
                messages.error(request, "Google sign-in accounts manage passwords through Google.")
            else:
                current_pw = request.POST.get("current_password", "")
                new_pw = request.POST.get("new_password", "")
                confirm_pw = request.POST.get("confirm_password", "")

                if not user.check_password(current_pw):
                    messages.error(request, "Current password is incorrect.")
                elif len(new_pw) < 8:
                    messages.error(request, "New password must be at least 8 characters long.")
                elif new_pw != confirm_pw:
                    messages.error(request, "New passwords do not match.")
                else:
                    user.set_password(new_pw)
                    user.save(update_fields=["password", "updated_at"])
                    update_session_auth_hash(request, user)
                    messages.success(request, "Password updated successfully.")
                    return redirect("operations:admin-settings")

        # 3. Platform & Marketplace Configuration
        elif form_type == "platform":
            raw_commission = request.POST.get("default_commission_rate", "5.00").strip()
            raw_fee = request.POST.get("monthly_subscription_fee", "250.00").strip()
            raw_payout_day = request.POST.get("payout_day_of_month", "28").strip()
            raw_cancel_hours = request.POST.get("cancellation_window_hours", "2").strip()
            support_email = request.POST.get("support_email", "").strip()
            support_whatsapp = request.POST.get("support_whatsapp", "").strip()
            maintenance_message = request.POST.get("maintenance_message", "").strip()

            try:
                commission_rate = Decimal(raw_commission)
                subscription_fee = Decimal(raw_fee)
                payout_day = max(1, min(28, int(raw_payout_day)))
                cancel_hours = max(0, int(raw_cancel_hours))
            except (InvalidOperation, ValueError):
                messages.error(request, "Please enter valid numeric values for fees, commission, and hours.")
                commission_rate = None

            if commission_rate is not None:
                if not support_email:
                    messages.error(request, "Support email is required.")
                else:
                    platform_settings.auto_approve_stores = request.POST.get("auto_approve_stores") == "on"
                    platform_settings.default_commission_rate = commission_rate
                    platform_settings.monthly_subscription_fee = subscription_fee # type: ignore
                    platform_settings.payout_day_of_month = payout_day # type: ignore
                    platform_settings.cancellation_window_hours = cancel_hours # type: ignore
                    platform_settings.allow_new_registrations = request.POST.get("allow_new_registrations") == "on"
                    platform_settings.support_email = support_email
                    platform_settings.support_whatsapp = support_whatsapp
                    platform_settings.notify_staff_new_store = request.POST.get("notify_staff_new_store") == "on"
                    platform_settings.notify_staff_urgent_complaint = request.POST.get("notify_staff_urgent_complaint") == "on"
                    platform_settings.maintenance_mode = request.POST.get("maintenance_mode") == "on"
                    platform_settings.maintenance_message = maintenance_message
                    platform_settings.updated_by = user
                    platform_settings.save()

                    messages.success(request, "Platform settings saved.")
                    return redirect("operations:admin-settings")

    return render(
        request,
        "operations/settings.html",
        {
            "profile": user,
            "platform_settings": platform_settings,
            "courses": User.Course.choices,
            "residences": User.Residence.choices,
            "is_email_auth": user.auth_provider == User.AuthProvider.EMAIL,
        },
    )