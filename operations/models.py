from decimal import Decimal, ROUND_HALF_UP
import uuid
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class CommissionPlan(models.Model):
    """
    Reusable monthly subscription/commission tiers (e.g., Standard 10%, Promo 5%).
    """
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("10.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
        help_text="Default percentage taken from store sales (e.g., 10.00 for 10%).",
    )
    monthly_base_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Optional fixed monthly subscription fee in MUR (0.00 for commission-only).",
    )
    default_trial_days = models.PositiveIntegerField(
        default=30,
        help_text="Default free-trial days granted to new stores on this plan.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["commission_rate", "name"]

    def __str__(self):
        return f"{self.name} ({self.commission_rate}%)"


class StoreSubscription(models.Model):
    """
    Tracks a store's active commission agreement, custom rate overrides,
    free trial period, and temporary grace periods.
    """
    class Status(models.TextChoices):
        TRIAL = "trial", "Free Trial"
        ACTIVE = "active", "Active"
        GRACE = "grace", "Grace Period"
        PAST_DUE = "past_due", "Past Due"
        SUSPENDED = "suspended", "Suspended"
        CANCELLED = "cancelled", "Cancelled"

    store = models.OneToOneField(
        "stores.Store",  # Adjust app_label.ModelName if your Store model lives elsewhere
        on_delete=models.CASCADE,
        related_name="subscription",
    )
    plan = models.ForeignKey(
        CommissionPlan,
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.TRIAL,
    )
    custom_commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
        help_text="Optional override for this specific store. Leave blank to use the plan rate.",
    )
    current_period_start = models.DateTimeField(default=timezone.now)
    current_period_end = models.DateTimeField()
    trial_ends_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Sales completed before this timestamp incur 0% commission.",
    )
    grace_period_ends_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Temporary commission-free grace window (e.g., onboarding delay or promo).",
    )
    grace_reason = models.CharField(
        max_length=255,
        blank=True,
        help_text="Internal note explaining why a grace period was granted.",
    )
    auto_renew = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-current_period_start"]

    def __str__(self):
        return f"{self.store.name} — {self.effective_commission_rate}% ({self.get_status_display()})" # type: ignore

    @property
    def base_commission_rate(self) -> Decimal:
        if self.custom_commission_rate is not None:
            return self.custom_commission_rate
        return self.plan.commission_rate

    def is_commission_waived(self, at_time=None) -> bool:
        """
        Returns True if a sale occurring at `at_time` falls within an active
        free trial or grace period.
        """
        check_time = at_time or timezone.now()
        if self.trial_ends_at and check_time <= self.trial_ends_at:
            return True
        if self.grace_period_ends_at and check_time <= self.grace_period_ends_at:
            return True
        return False

    def get_rate_for_timestamp(self, at_time=None) -> Decimal:
        """Returns 0.00 during trial/grace period, otherwise the store's rate."""
        if self.is_commission_waived(at_time):
            return Decimal("0.00")
        return self.base_commission_rate

    @property
    def effective_commission_rate(self) -> Decimal:
        return self.get_rate_for_timestamp(timezone.now())


class Payout(models.Model):
    """
    Monthly (or periodic) settlement statement and disbursement record for a store.
    """
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending Approval"
        PROCESSING = "processing", "Processing Transfer"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        ON_HOLD = "on_hold", "On Hold"

    reference = models.CharField(max_length=32, unique=True, editable=False)
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.PROTECT,
        related_name="payouts",
    )
    subscription = models.ForeignKey(
        StoreSubscription,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payouts",
    )
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()

    # Financial breakdown (MUR)
    gross_sales = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Total completed sales in this period.",
    )
    exempt_sales = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Sales covered by a free trial or grace period (0% commission).",
    )
    commissionable_sales = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Sales subject to platform commission.",
    )
    applied_commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("10.00"),
        help_text="Snapshot of the store's commission % when this payout was generated.",
    )
    commission_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Total commission deducted by The Spotlight.",
    )
    subscription_fee_deducted = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Optional fixed monthly subscription fee deducted from payout.",
    )
    adjustments = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Manual credits (+) or dispute/refund deductions (-).",
    )
    net_payout = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Final amount transferred to the vendor.",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    payment_method = models.CharField(
        max_length=50,
        blank=True,
        help_text="e.g., Bank Transfer (MCB / SBM), Juice, Manual",
    )
    transaction_reference = models.CharField(
        max_length=120,
        blank=True,
        help_text="Bank transfer ID or receipt reference.",
    )
    notes = models.TextField(blank=True)

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_payouts",
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period_end", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["store", "period_start", "period_end"],
                name="unique_store_payout_period",
            )
        ]

    def __str__(self):
        return f"{self.reference} — {self.store.name} (MUR {self.net_payout})"

    def save(self, *args, **kwargs):
        if not self.reference:
            timestamp_part = timezone.now().strftime("%Y%m")
            import uuid
            self.reference = f"PAY-{timestamp_part}-{uuid.uuid4().hex[:6].upper()}"
        super().save(*args, **kwargs)

    def recalculate_totals(self, save=True):
        """
        Aggregates all attached PayoutItems and computes commission + net payout.
        """
        items = self.items.all() # type: ignore
        gross = Decimal("0.00")
        exempt = Decimal("0.00")
        commission_total = Decimal("0.00")

        for item in items:
            gross += item.gross_amount
            if item.is_waived:
                exempt += item.gross_amount
            commission_total += item.commission_amount

        self.gross_sales = gross
        self.exempt_sales = exempt
        self.commissionable_sales = gross - exempt
        self.commission_amount = commission_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.net_payout = (
            self.gross_sales
            - self.commission_amount
            - self.subscription_fee_deducted
            + self.adjustments
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if save:
            self.save(
                update_fields=[
                    "gross_sales",
                    "exempt_sales",
                    "commissionable_sales",
                    "commission_amount",
                    "net_payout",
                    "updated_at",
                ]
            )


class PayoutItem(models.Model):
    """
    Individual completed Order or Booking included in a Payout.
    OneToOneField guarantees a sale can never be paid out twice.
    """
    payout = models.ForeignKey(
        Payout,
        on_delete=models.CASCADE,
        related_name="items",
    )
    order = models.OneToOneField(
        "transactions.Order",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payout_item",
    )
    booking = models.OneToOneField(
        "transactions.Booking",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payout_item",
    )
    gross_amount = models.DecimalField(max_digits=10, decimal_places=2)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2)
    commission_amount = models.DecimalField(max_digits=10, decimal_places=2)
    is_waived = models.BooleanField(
        default=False,
        help_text="True if covered by free trial or grace period at the time of sale.",
    )
    waiver_reason = models.CharField(
        max_length=50,
        blank=True,
        help_text="e.g., 'free_trial' or 'grace_period'",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(order__isnull=False, booking__isnull=True)
                    | models.Q(order__isnull=True, booking__isnull=False)
                ),
                name="payout_item_exactly_one_source",
            )
        ]

    def __str__(self):
        source = self.order or self.booking
        return f"{self.payout.reference} -> {source} (MUR {self.gross_amount})"
    

class Complaint(models.Model):
    """
    Tracks customer or vendor complaints, order/booking disputes, and policy reports.
    """
    class Category(models.TextChoices):
        ORDER_ISSUE = "order_issue", "Order Issue (Missing / Late / Wrong)"
        BOOKING_ISSUE = "booking_issue", "Booking / Service Dispute"
        PAYMENT_REFUND = "payment_refund", "Payment or Refund"
        STORE_CONDUCT = "store_conduct", "Vendor Conduct / Policy Violation"
        REVIEW_ABUSE = "review_abuse", "Abusive or Fake Review"
        TECHNICAL = "technical", "Platform / Technical Bug"
        OTHER = "other", "Other"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "Under Investigation"
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Dismissed"

    reference = models.CharField(max_length=24, unique=True, editable=False)

    # Who submitted it & who is handling it
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="filed_complaints",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"is_staff": True},
        related_name="assigned_complaints",
    )

    # Optional linked marketplace entities
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="complaints",
    )
    order = models.ForeignKey(
        "transactions.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="complaints",
    )
    booking = models.ForeignKey(
        "transactions.Booking",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="complaints",
    )
    review = models.ForeignKey(
        "stores.Review",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="complaints",
    )

    # Details
    category = models.CharField(
        max_length=24,
        choices=Category.choices,
        default=Category.ORDER_ISSUE,
        db_index=True,
    )
    priority = models.CharField(
        max_length=12,
        choices=Priority.choices,
        default=Priority.MEDIUM,
        db_index=True,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    subject = models.CharField(max_length=180)
    description = models.TextField()
    evidence = models.FileField(
        upload_to="operations/complaints/",
        blank=True,
        null=True,
        help_text="Optional screenshot or receipt uploaded by the reporter.",
    )

    # Admin resolution
    resolution_notes = models.TextField(
        blank=True,
        default="",
        help_text="Internal summary of investigation findings and action taken.",
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_complaints",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "priority", "-created_at"]),
            models.Index(fields=["store", "status"]),
        ]

    def __str__(self):
        return f"{self.reference} — {self.subject}"

    @property
    def is_open(self) -> bool:
        return self.status in (self.Status.OPEN, self.Status.IN_PROGRESS)

    def save(self, *args, **kwargs):
        if not self.reference:
            stamp = timezone.now().strftime("%y%m")
            self.reference = f"CMP-{stamp}-{uuid.uuid4().hex[:5].upper()}"
        super().save(*args, **kwargs)

    def mark_resolved(self, admin_user, notes: str = "", dismissed: bool = False):
        self.status = self.Status.DISMISSED if dismissed else self.Status.RESOLVED
        if notes:
            self.resolution_notes = notes
        self.resolved_by = admin_user
        self.resolved_at = timezone.now()
        self.save(
            update_fields=[
                "status",
                "resolution_notes",
                "resolved_by",
                "resolved_at",
                "updated_at",
            ]
        )


class AdminNotification(models.Model):
    """
    System alerts surfaced to the operations team (new store applications,
    complaints, payout runs, flagged reviews, etc.).
    """
    class Level(models.TextChoices):
        INFO = "info", "Info"
        SUCCESS = "success", "Success"
        WARNING = "warning", "Action Required"
        DANGER = "danger", "Urgent Alert"

    class Category(models.TextChoices):
        STORE = "store", "Store Approval"
        COMPLAINT = "complaint", "Complaint / Dispute"
        PAYOUT = "payout", "Payout & Commission"
        ORDER = "order", "Order / Booking"
        ADVERTISING = "advertising", "Ads & Announcements"
        SYSTEM = "system", "System"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        limit_choices_to={"is_staff": True},
        related_name="admin_notifications",
        help_text="Leave blank for a shared operations-wide alert visible to all staff.",
    )
    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.SYSTEM,
        db_index=True,
    )
    level = models.CharField(
        max_length=12,
        choices=Level.choices,
        default=Level.INFO,
    )
    title = models.CharField(max_length=160)
    message = models.TextField(blank=True, default="")
    action_url = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Optional operations URL to jump directly to the item.",
    )
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    read_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="read_admin_notifications",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["is_read", "-created_at"]
        indexes = [
            models.Index(fields=["is_read", "-created_at"]),
            models.Index(fields=["recipient", "is_read"]),
        ]

    def __str__(self):
        return f"[{self.get_category_display()}] {self.title}" # type: ignore

    def mark_as_read(self, user=None):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.read_by = user
            self.save(update_fields=["is_read", "read_at", "read_by"])


class BroadcastAnnouncement(models.Model):
    """
    Outgoing platform announcements/notifications sent by admins to
    customers, store owners, or everyone on The Spotlight.
    """
    class Audience(models.TextChoices):
        ALL = "all", "All Users"
        CUSTOMERS = "customers", "Students / Customers Only"
        VENDORS = "vendors", "Store Owners Only"

    title = models.CharField(max_length=160)
    body = models.TextField()
    audience = models.CharField(
        max_length=16,
        choices=Audience.choices,
        default=Audience.ALL,
    )
    is_pinned = models.BooleanField(
        default=False,
        help_text="Pin to the top of user feeds / dashboard banners.",
    )
    send_email = models.BooleanField(
        default=False,
        help_text="Also dispatch via email to the target audience.",
    )
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="sent_broadcasts",
    )
    published_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_pinned", "-published_at"]

    def __str__(self):
        return f"{self.title} ({self.get_audience_display()})" # type: ignore

class PlatformSettings(models.Model):
    """Singleton configuration record (pk=1) for The Spotlight marketplace."""

    # Store & Vendor Rules
    auto_approve_stores = models.BooleanField(
        default=False,
        help_text="Automatically approve newly submitted store applications.",
    )
    default_commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("5.00"),
        help_text="Default platform commission percentage (%).",
    )
    monthly_subscription_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("250.00"),
        help_text="Standard monthly vendor subscription fee (MUR).",
    )
    payout_day_of_month = models.PositiveSmallIntegerField(
        default=28,
        help_text="Day of the month (1–28) when vendor payouts are processed.",
    )

    # Orders & Bookings
    cancellation_window_hours = models.PositiveSmallIntegerField(
        default=2,
        help_text="Minimum hours before a booking slot that customers can cancel.",
    )
    allow_new_registrations = models.BooleanField(
        default=True,
        help_text="Allow new student and vendor accounts to sign up.",
    )

    # Support & Operations Alerts
    support_email = models.EmailField(
        default="support@thespotlight.mu",
        help_text="Public support email displayed on order receipts and complaints.",
    )
    support_whatsapp = models.CharField(
        max_length=25,
        blank=True,
        default="+230 5000 0000",
        help_text="Operations support WhatsApp contact number.",
    )
    notify_staff_new_store = models.BooleanField(
        default=True,
        help_text="Send an operations alert when a new store submits an application.",
    )
    notify_staff_urgent_complaint = models.BooleanField(
        default=True,
        help_text="Send an operations alert when a high-priority complaint is filed.",
    )

    # Maintenance Banner
    maintenance_mode = models.BooleanField(
        default=False,
        help_text="Display a platform-wide maintenance notice banner to non-staff users.",
    )
    maintenance_message = models.CharField(
        max_length=255,
        blank=True,
        default="The Spotlight is undergoing scheduled maintenance. Some features may be temporarily unavailable.",
    )

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "Platform Settings"
        verbose_name_plural = "Platform Settings"

    def __str__(self):
        return "The Spotlight — Platform Settings"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj