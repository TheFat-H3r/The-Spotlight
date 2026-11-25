from stores.models import Store
from transactions.models import Booking, Order
from .models import Payout


def operations_sidebar_counts(request):
    
    if not request.path.startswith("/portal/") or not getattr(request.user, "is_staff", False):
        return {}

    pending_store_approvals = Store.objects.filter(status=Store.Status.DRAFT).count()
    pending_order_count = Order.objects.filter(status="pending").count()
    pending_booking_count = Booking.objects.filter(status="pending").count()
    pending_payout_count = Payout.objects.filter(
        status__in=[Payout.Status.DRAFT, Payout.Status.PENDING]
    ).count()

    
    pending_ad_approvals = 0
    open_complaints_count = 0
    unread_notifications_count = 0

    try:
        from marketing.models import Advertisement 
        pending_ad_approvals = Advertisement.objects.filter(status="pending").count()
    except Exception:
        pass

    try:
        from operations.models import Complaint, AdminNotification  # adjust if defined elsewhere
        open_complaints_count = Complaint.objects.filter(status__in=["open", "in_progress"]).count()
        unread_notifications_count = AdminNotification.objects.filter(is_read=False).count()
    except Exception:
        pass

    total_attention_count = (
        pending_store_approvals
        + pending_ad_approvals
        + open_complaints_count
        + pending_order_count
        + pending_booking_count
        + pending_payout_count
        + unread_notifications_count
    )

    return {
        "pending_store_approvals": pending_store_approvals,
        "pending_ad_approvals": pending_ad_approvals,
        "open_complaints_count": open_complaints_count,
        "pending_order_count": pending_order_count,
        "pending_booking_count": pending_booking_count,
        "pending_payout_count": pending_payout_count,
        "unread_notifications_count": unread_notifications_count,
        "ops_total_attention_count": total_attention_count,
    }