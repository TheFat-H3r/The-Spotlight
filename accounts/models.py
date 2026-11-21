from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models
from django.utils import timezone
from django.core.validators import RegexValidator
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.utils.text import slugify

from stores.models import Store


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

    class Residence(models.TextChoices):
        MAPS = "Maps", "Maps"
        SONGHAI = "Songhai", "Songhai"
        KONGO = "Kongo", "Kongo"
        AKSUM = "Aksum", "Aksum"
    
    class Course(models.TextChoices):
        CS = "CS", "CS"
        SE = "SE", "SE"
        EL = "EL", "EL"
        IBT = "IBT", "IBT"

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

    # Locating
    course = models.CharField(max_length=4, choices=Course.choices, blank=True, help_text="Your course of study.")
    cohort = models.CharField(
            max_length=4,
            blank=True,
            validators=[
                RegexValidator(
                    regex=r"^[A-Z]'\d{2}$",
                    message="Cohort must strictly match the format F'25 (uppercase letter, apostrophe, and 2 digits).",
                )
            ],
            help_text="Format: F'25",
        )
    residence = models.CharField(
            max_length=20,
            choices=Residence.choices,
            blank=True,
            help_text="Campus residence hall.",
        )
    room_number = models.CharField(
            max_length=4,
            blank=True,
            validators=[
                RegexValidator(
                    regex=r"^[A-Z]\d{3}$",
                    message="Room number must strictly match the format S101 (1 uppercase letter followed by 3 digits).",
                )
            ],
            help_text="Format: S101",
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

    def generate_password_reset_token(self) -> str:
        """Generates a signed token containing user PK and a password hash fragment."""
        signer = TimestampSigner(salt="password-reset")
        # Including password[-10:] invalidates the token immediately once password changes
        payload = f"{self.pk}:{self.password[-10:]}"
        return signer.sign(payload)

    @staticmethod
    def verify_password_reset_token(token: str, max_age: int = 600):
        """
        Verifies password reset token within max_age (default: 600s / 10 minutes).
        Returns User instance if valid and password hasn't changed since issuance.
        """
        signer = TimestampSigner(salt="password-reset")
        try:
            unsigned_data = signer.unsign(token, max_age=max_age)
            user_id, pwd_fragment = unsigned_data.split(":", 1)
            user = User.objects.get(pk=user_id)
            if user.password[-10:] == pwd_fragment:
                return user
            return None
        except (BadSignature, SignatureExpired, ValueError, User.DoesNotExist):
            return None
