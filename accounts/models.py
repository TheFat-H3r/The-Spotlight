from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.core.validators import RegexValidator
from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from django.utils.text import slugify
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired


class UserManager(BaseUserManager):
    """Manager for a User model that logs in with email instead of username."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("role", User.Role.CUSTOMER)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_email_verified", True)
        extra_fields.setdefault("role", User.Role.ADMIN)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Spotlight user. One model, three roles: customer, vendor, admin."""

    class Role(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        VENDOR = "vendor", "Vendor"
        ADMIN = "admin", "Administrator"

    class AuthProvider(models.TextChoices):
        EMAIL = "email", "Email & password"
        GOOGLE = "google", "Google"

    phone_validator = RegexValidator(
        regex=r"^\+?\d{7,15}$",
        message="Enter a valid phone number (7-15 digits, optional leading +).",
    )

    # Identity
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150)
    phone = models.CharField(
        max_length=16, blank=True, validators=[phone_validator]
    )
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)

    # Campus info (optional; useful for trust and vendor verification)
    student_id = models.CharField(max_length=30, blank=True)

    # Sign-in method (Google users have no usable password)
    auth_provider = models.CharField(
        max_length=10, choices=AuthProvider.choices, default=AuthProvider.EMAIL
    )
    google_id = models.CharField(
        max_length=64, unique=True, null=True, blank=True
    )

    # Access control
    role = models.CharField(
        max_length=10, choices=Role.choices, default=Role.CUSTOMER, db_index=True
    )

    # Status flags
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)  # Django admin site access
    is_email_verified = models.BooleanField(default=False)

    # Timestamps
    date_joined = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta: # type: ignore
        ordering = ["-date_joined"]

    def __str__(self):
        return self.email

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.full_name.split(" ")[0] if self.full_name else self.email

    # Convenience role checks (use these in permission classes)
    @property
    def is_customer(self):
        return self.role == self.Role.CUSTOMER

    @property
    def is_vendor(self):
        return self.role == self.Role.VENDOR

    @property
    def is_platform_admin(self):
        return self.role == self.Role.ADMIN

    def generate_email_verification_token(self) -> str:
        """Generates a cryptographically signed token containing user's PK."""
        signer = TimestampSigner()
        return signer.sign(self.pk)

    @staticmethod
    def verify_email_token(token: str, max_age: int = 600):
        """
        Verifies token within max_age (default: 600s / 10 minutes).
        Returns User instance if valid, None if invalid or expired.
        """
        signer = TimestampSigner()
        try:
            user_id = signer.unsign(token, max_age=max_age)
            return User.objects.get(pk=user_id)
        except (BadSignature, SignatureExpired, User.DoesNotExist):
            return None


# ---------------------------------------------------------------------------
# Customer profile (every user gets one automatically, see signals.py)
# ---------------------------------------------------------------------------
class CustomerProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_profile",
    )
    department = models.CharField(max_length=100, blank=True)
    year_of_study = models.PositiveSmallIntegerField(null=True, blank=True)
    campus_location = models.CharField(
        max_length=120,
        blank=True,
        help_text="Hostel, block or usual meet-up point on campus.",
    )
    bio = models.TextField(max_length=300, blank=True)

    # Notification preferences
    receive_promotions = models.BooleanField(default=True)
    receive_email_notifications = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Customer profile: {self.user.email}"


# ---------------------------------------------------------------------------
# Vendor profile (created only when a VendorApplication is approved)
# ---------------------------------------------------------------------------
class VendorProfile(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="vendor_profile",
    )

    # Business identity
    business_name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, unique=True)
    tagline = models.CharField(max_length=160, blank=True)
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to="vendors/logos/", blank=True, null=True)
    banner = models.ImageField(upload_to="vendors/banners/", blank=True, null=True)

    # Contact (shown publicly on the storefront)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=16, blank=True)
    whatsapp = models.CharField(max_length=16, blank=True)
    social_links = models.JSONField(
        default=dict, blank=True, help_text='e.g. {"instagram": "https://..."}'
    )

    # Trust and moderation
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )

    # Denormalised reputation (updated by the reviews app)
    rating_average = models.DecimalField(max_digits=3, decimal_places=2, default=0) # type: ignore
    rating_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["business_name"]

    def __str__(self):
        return self.business_name

    @property
    def is_active_vendor(self):
        return self.status == self.Status.ACTIVE

    @staticmethod
    def generate_unique_slug(name):
        base = slugify(name)[:150] or "vendor"
        slug, n = base, 2
        while VendorProfile.objects.filter(slug=slug).exists():
            slug = f"{base}-{n}"
            n += 1
        return slug


# ---------------------------------------------------------------------------
# Vendor application (customer asks to become a vendor; admin reviews it)
# ---------------------------------------------------------------------------
class VendorApplication(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    class BusinessType(models.TextChoices):
        PRODUCTS = "products", "Sells products"
        SERVICES = "services", "Offers services"
        BOTH = "both", "Products and services"

    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="vendor_applications",
    )

    # What the applicant submits
    business_name = models.CharField(max_length=150)
    business_type = models.CharField(max_length=10, choices=BusinessType.choices)
    description = models.TextField(help_text="What do you sell or offer?")
    contact_phone = models.CharField(max_length=16, blank=True)
    proof_document = models.FileField(
        upload_to="vendor_applications/",
        blank=True,
        null=True,
        help_text="Student ID, business registration or similar.",
    )

    # Review outcome
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    rejection_reason = models.TextField(blank=True)
    admin_notes = models.TextField(blank=True, help_text="Internal only.")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_vendor_applications",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-submitted_at"]
        constraints = [
            # A user can have only one pending application at a time,
            # but may re-apply after a rejection.
            models.UniqueConstraint(
                fields=["applicant"],
                condition=models.Q(status="pending"),
                name="unique_pending_application_per_user",
            )
        ]

    def __str__(self):
        return f"{self.business_name} ({self.get_status_display()})" # type: ignore

    def approve(self, admin_user, notes=""):
        """Approve: promote the applicant to vendor and create their VendorProfile."""
        if self.status != self.Status.PENDING:
            raise ValueError("Only pending applications can be approved.")

        with transaction.atomic():
            now = timezone.now()
            user = self.applicant

            VendorProfile.objects.get_or_create(
                user=user,
                defaults={
                    "business_name": self.business_name,
                    "slug": VendorProfile.generate_unique_slug(self.business_name),
                    "description": self.description,
                    "contact_email": user.email,
                    "contact_phone": self.contact_phone,
                    "is_verified": True,
                    "verified_at": now,
                },
            )
            user.role = User.Role.VENDOR
            user.save(update_fields=["role", "updated_at"])

            self.status = self.Status.APPROVED
            self.reviewed_by = admin_user
            self.reviewed_at = now
            if notes:
                self.admin_notes = notes
            self.save()

    def reject(self, admin_user, reason, notes=""):
        """Reject with a reason the applicant can see."""
        if self.status != self.Status.PENDING:
            raise ValueError("Only pending applications can be rejected.")
        if not reason:
            raise ValueError("A rejection reason is required.")

        self.status = self.Status.REJECTED
        self.rejection_reason = reason
        self.reviewed_by = admin_user
        self.reviewed_at = timezone.now()
        if notes:
            self.admin_notes = notes
        self.save()