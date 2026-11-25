from stores.models import Product, Service, Store
from transactions.models import Booking, Order, VendorNotification


def _resolve_business_mode(store):
    """
    Returns 'service', 'product', or 'both' based on store.business_type.store_type.
    """
    if not store:
        return "product"

    bt = getattr(store, "business_type", None)
    if bt is None:
        return "product"

    # Extract store_type from the business_type object (or dict if serialized)
    st = bt.get("store_type") if isinstance(bt, dict) else getattr(bt, "store_type", None)
    if st is None:
        return "product"

    # Extract string identifier whether store_type is a CharField/enum or a related object
    raw_value = ""
    if isinstance(st, str):
        raw_value = st.lower()
    else:
        for attr in ("slug", "code", "kind", "category_type", "name"):
            val = getattr(st, attr, None)
            if val:
                raw_value = str(val).lower()
                break
        if not raw_value:
            raw_value = str(st).lower()

    if any(k in raw_value for k in ("service", "booking", "salon", "barber", "appointment", "tutor", "consult")):
        return "service"
    if any(k in raw_value for k in ("both", "hybrid")):
        return "both"
    return "product"


def vendor_dashboard_context(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}

    user = request.user
    full_name = getattr(user, "full_name", "") or user.get_full_name()
    vendor_display_name = full_name or getattr(user, "username", "") or user.email

    # Resolve profile avatar
    vendor_avatar_url = None
    for obj in (user, getattr(user, "vendor_profile", None), getattr(user, "vendorprofile", None)):
        if not obj:
            continue
        for field in ("avatar", "profile_picture", "photo", "image", "logo"):
            img = getattr(obj, field, None)
            if img and getattr(img, "url", None):
                vendor_avatar_url = img.url
                break
        if vendor_avatar_url:
            break

    # Vendor has one primary store
    vendor_store = (
        Store.objects.filter(owner=user)
        .select_related("business_type")
        .first()
    )
    business_mode = _resolve_business_mode(vendor_store)
    is_service_business = business_mode in ("service", "both")
    is_product_business = business_mode in ("product", "both")

    if not vendor_store:
        return {
            "vendor_display_name": vendor_display_name,
            "vendor_avatar_url": vendor_avatar_url,
            "vendor_store": None,
            "business_mode": business_mode,
            "is_service_business": is_service_business,
            "is_product_business": is_product_business,
            "unread_notifications_count": 0,
            "recent_header_notifications": [],
            "pending_orders_count": 0,
            "pending_bookings_count": 0,
            "pending_listing_approvals_count": 0,
        }

    notifications_qs = (
        VendorNotification.objects.filter(store=vendor_store)
        .select_related("store", "order")
        .order_by("-created_at")
    )
    unread_notifications_count = notifications_qs.filter(is_read=False).count()
    recent_header_notifications = list(notifications_qs[:5])

    pending_orders_count = (
        Order.objects.filter(store=vendor_store, status=Order.Status.PENDING).count()
        if is_product_business
        else 0
    )

    pending_bookings_count = (
        Booking.objects.filter(service__store=vendor_store, status=Booking.Status.PENDING).count()
        if is_service_business
        else 0
    )

    pending_listing_approvals_count = 0
    if is_product_business and hasattr(Product, "approval_status"):
        pending_listing_approvals_count += Product.objects.filter(
            store=vendor_store, approval_status="pending"
        ).count()
    if is_service_business and hasattr(Service, "approval_status"):
        pending_listing_approvals_count += Service.objects.filter(
            store=vendor_store, approval_status="pending"
        ).count()

    return {
        "vendor_display_name": vendor_display_name,
        "vendor_avatar_url": vendor_avatar_url,
        "vendor_store": vendor_store,
        "business_mode": business_mode,
        "is_service_business": is_service_business,
        "is_product_business": is_product_business,
        "unread_notifications_count": unread_notifications_count,
        "recent_header_notifications": recent_header_notifications,
        "pending_orders_count": pending_orders_count,
        "pending_bookings_count": pending_bookings_count,
        "pending_listing_approvals_count": pending_listing_approvals_count,
    }