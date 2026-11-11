from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from marketplace.models import unique_slug
from orders.models import Order
from products.models import Product

MAX_GALLERY_IMAGES = 30


def unique_slug_within(model_class, value, scope_field, scope_value, instance=None, max_length=150):
    """Slug that is unique among rows sharing `scope_field` (e.g. one venture's projects)."""
    base = slugify(value)[: max_length - 6] or model_class._meta.model_name
    queryset = model_class.objects.filter(**{scope_field: scope_value})
    if instance is not None and instance.pk:
        queryset = queryset.exclude(pk=instance.pk)

    slug, n = base, 2
    while queryset.filter(slug=slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


# ---------------------------------------------------------------------------
# VentureProfile (the public page for a student business)
# ---------------------------------------------------------------------------
class VentureQuerySet(models.QuerySet):
    def public(self):
        """Ventures that customers are allowed to see."""
        return self.filter(
            status=VentureProfile.Status.PUBLISHED,
            vendor__status="active",
            vendor__user__is_active=True,
        )


class VentureProfile(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft (not public)"
        PENDING = "pending", "Awaiting review"
        PUBLISHED = "published", "Published"
        HIDDEN = "hidden", "Hidden by admin"

    vendor = models.OneToOneField(
        "accounts.VendorProfile", on_delete=models.CASCADE, related_name="venture"
    )
    store = models.ForeignKey(
        "marketplace.Store",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ventures",
        help_text='Optional store to link from the page ("Shop this venture").',
    )

    # Identity
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, unique=True, blank=True)
    tagline = models.CharField(max_length=160, blank=True)
    story = models.TextField(blank=True, help_text="The venture's story: what, why, who for.")
    logo = models.ImageField(upload_to="ventures/logos/", blank=True, null=True)
    cover_image = models.ImageField(upload_to="ventures/covers/", blank=True, null=True)
    category = models.ForeignKey(
        "marketplace.Category",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ventures",
    )

    # About the team
    founded_year = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1900), MaxValueValidator(2100)],
    )
    faculty = models.CharField(
        max_length=100, blank=True, help_text="School, faculty or programme on campus."
    )
    team_members = models.JSONField(
        default=list,
        blank=True,
        help_text='e.g. [{"name": "Aisha K.", "role": "Founder"}]',
    )

    # Links
    website = models.URLField(blank=True)
    social_links = models.JSONField(
        default=dict,
        blank=True,
        help_text='e.g. {"instagram": "https://...", "tiktok": "https://..."}',
    )

    # Visibility and review
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    review_note = models.CharField(
        max_length=255, blank=True, help_text="Admin feedback when a submission is sent back."
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    view_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = VentureQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["status", "published_at"])]

    def __str__(self):
        return self.name

    # -- helpers ------------------------------------------------------------
    @property
    def is_public(self):
        return (
            self.status == self.Status.PUBLISHED
            and self.vendor.status == "active"
            and self.vendor.user.is_active
        )

    def get_stats(self):
        """Live numbers for the page header, pulled from the rest of the platform."""
        vendor = self.vendor
        reputation = getattr(vendor, "reputation", None)
        return {
            "completed_orders": Order.objects.filter(
                store__vendor=vendor, status=Order.Status.COMPLETED
            ).count(),
            "active_products": Product.objects.public().filter(store__vendor=vendor).count(), # type: ignore
            "rating_average": reputation.rating_average if reputation else 0,
            "rating_count": reputation.rating_count if reputation else 0,
            "projects": self.projects.filter(is_visible=True).count(),  # type: ignore
        }

    def clean(self):
        if self.store_id and self.vendor_id and self.store.vendor_id != self.vendor_id:  # type: ignore
            raise ValidationError({"store": "This store belongs to a different vendor."})

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(VentureProfile, self.name, self, max_length=160)
        super().save(*args, **kwargs)

    # -- publishing workflow ------------------------------------------------
    def missing_for_review(self):
        """What a student still has to fill in before submitting."""
        missing = []
        if not self.tagline:
            missing.append("tagline")
        if len(self.story.strip()) < 50:
            missing.append("story (at least 50 characters)")
        if not (self.logo or self.cover_image):
            missing.append("logo or cover image")
        return missing

    def submit_for_review(self):
        if self.status not in (self.Status.DRAFT,):
            raise ValidationError("Only a draft can be submitted for review.")
        missing = self.missing_for_review()
        if missing:
            raise ValidationError("Please add: " + ", ".join(missing) + ".")
        self.status = self.Status.PENDING
        self.review_note = ""
        self.save(update_fields=["status", "review_note", "updated_at"])

    def publish(self, by=None):
        self.status = self.Status.PUBLISHED
        self.reviewed_by = by
        self.reviewed_at = timezone.now()
        self.review_note = ""
        if self.published_at is None:
            self.published_at = self.reviewed_at
        self.save(
            update_fields=[
                "status",
                "reviewed_by",
                "reviewed_at",
                "review_note",
                "published_at",
                "updated_at",
            ]
        )

    def send_back(self, by=None, note=""):
        """Return a submission to draft with feedback for the student."""
        self.status = self.Status.DRAFT
        self.reviewed_by = by
        self.reviewed_at = timezone.now()
        self.review_note = note[:255]
        self.save(
            update_fields=["status", "reviewed_by", "reviewed_at", "review_note", "updated_at"]
        )

    def hide(self, by=None, note=""):
        self.status = self.Status.HIDDEN
        self.reviewed_by = by
        self.reviewed_at = timezone.now()
        self.review_note = note[:255]
        self.save(
            update_fields=["status", "reviewed_by", "reviewed_at", "review_note", "updated_at"]
        )


# ---------------------------------------------------------------------------
# Project (something the venture has built, launched or run)
# ---------------------------------------------------------------------------
class ProjectQuerySet(models.QuerySet):
    def visible(self):
        """Visible projects of ventures that are themselves public."""
        return self.filter(
            is_visible=True,
            venture__status=VentureProfile.Status.PUBLISHED,
            venture__vendor__status="active",
            venture__vendor__user__is_active=True,
        )


class Project(models.Model):
    class ProjectType(models.TextChoices):
        PRODUCT = "product", "Product launch"
        SERVICE = "service", "Service / client work"
        EVENT = "event", "Event"
        CAMPAIGN = "campaign", "Campaign"
        COLLAB = "collaboration", "Collaboration"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"

    venture = models.ForeignKey(
        VentureProfile, on_delete=models.CASCADE, related_name="projects"
    )

    title = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, blank=True)
    summary = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    cover_image = models.ImageField(upload_to="ventures/projects/", blank=True, null=True)

    project_type = models.CharField(
        max_length=15, choices=ProjectType.choices, default=ProjectType.PRODUCT
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.COMPLETED
    )
    started_on = models.DateField(null=True, blank=True)
    completed_on = models.DateField(null=True, blank=True)
    collaborators = models.CharField(
        max_length=200, blank=True, help_text="Clients, partners or teammates, comma-separated."
    )
    project_url = models.URLField(blank=True)
    tags = models.JSONField(default=list, blank=True)

    is_featured = models.BooleanField(
        default=False, help_text="Pin to the top of the venture page."
    )
    is_visible = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProjectQuerySet.as_manager()

    class Meta:
        ordering = ["-is_featured", "display_order", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["venture", "slug"], name="unique_project_slug_per_venture"
            ),
            models.UniqueConstraint(
                fields=["venture", "title"], name="unique_project_title_per_venture"
            ),
        ]
        indexes = [models.Index(fields=["venture", "is_visible"])]

    def __str__(self):
        return f"{self.title} ({self.venture})"

    def clean(self):
        if self.started_on and self.completed_on and self.completed_on < self.started_on:
            raise ValidationError({"completed_on": "Cannot be before the start date."})

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug_within(
                Project, self.title, "venture_id", self.venture.id, self, max_length=160
            )
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# GalleryImage (venture-wide photos, or photos of one project)
# ---------------------------------------------------------------------------
class GalleryImage(models.Model):
    venture = models.ForeignKey(
        VentureProfile, on_delete=models.CASCADE, related_name="gallery"
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="gallery",
        help_text="Leave empty for the venture's general gallery.",
    )
    image = models.ImageField(upload_to="ventures/gallery/")
    caption = models.CharField(max_length=200, blank=True)
    alt_text = models.CharField(max_length=150, blank=True)
    display_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_order", "id"]
        indexes = [models.Index(fields=["venture", "project"])]

    def __str__(self):
        return f"Gallery image for {self.venture}"

    def clean(self):
        errors = {}
        if self.project_id and self.venture_id and self.project.venture_id != self.venture_id:  # type: ignore
            errors["project"] = "This project belongs to a different venture."
        if (
            self._state.adding
            and self.venture_id  # type: ignore
            and GalleryImage.objects.filter(venture_id=self.venture_id).count()  # type: ignore
            >= MAX_GALLERY_IMAGES
        ):
            errors["image"] = f"A venture can have at most {MAX_GALLERY_IMAGES} gallery images."
        if errors:
            raise ValidationError(errors)


# ---------------------------------------------------------------------------
# Achievement (awards, milestones, press...)
# ---------------------------------------------------------------------------
class Achievement(models.Model):
    class Kind(models.TextChoices):
        AWARD = "award", "Award"
        COMPETITION = "competition", "Competition / pitch"
        MILESTONE = "milestone", "Milestone"
        PRESS = "press", "Press / feature"
        CERTIFICATION = "certification", "Certification / programme"

    class Source(models.TextChoices):
        SELF_REPORTED = "self", "Added by the student"
        PLATFORM = "platform", "Earned on Spotlight"

    venture = models.ForeignKey(
        VentureProfile, on_delete=models.CASCADE, related_name="achievements"
    )
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    kind = models.CharField(max_length=15, choices=Kind.choices, default=Kind.MILESTONE)
    issuer = models.CharField(
        max_length=150, blank=True, help_text="Who awarded it, e.g. the competition or publication."
    )
    achieved_on = models.DateField(null=True, blank=True)
    url = models.URLField(blank=True, help_text="Link to proof, e.g. an article.")
    badge_image = models.ImageField(upload_to="ventures/achievements/", blank=True, null=True)
    display_order = models.PositiveIntegerField(default=0)

    # Self-reported claims show a "verified" tick once an admin has checked them.
    source = models.CharField(
        max_length=10, choices=Source.choices, default=Source.SELF_REPORTED
    )
    is_verified = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "-achieved_on", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["venture", "title"], name="unique_achievement_title_per_venture"
            )
        ]

    def __str__(self):
        return f"{self.title} ({self.venture})"

    def save(self, *args, **kwargs):
        if self.source == self.Source.PLATFORM:
            self.is_verified = True
        super().save(*args, **kwargs)