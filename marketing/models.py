from django.conf import settings
from django.db import models
from django.utils.text import slugify
from stores.models import Store


class Advertisement(models.Model):
  class Status(models.TextChoices):
    PENDING = 'pending', 'Pending Approval'
    ACTIVE = 'active', 'Active'
    PAUSED = 'paused', 'Paused'
    EXPIRED = 'expired', 'Expired'
    REJECTED = 'rejected', 'Rejected'

  # Foreign Keys requested
  user = models.ForeignKey(
      settings.AUTH_USER_MODEL,
      on_delete=models.CASCADE,
      related_name='advertisements',
      help_text='The user account managing or creating the ad.',
  )
  store = models.ForeignKey(
      Store,
      on_delete=models.CASCADE,
      related_name='advertisements',
      help_text='The store being promoted by this advertisement.',
  )

  # Ad Content Details
  title = models.CharField(max_length=200)
  slug = models.SlugField(max_length=220, unique=True, blank=True)
  description = models.TextField(blank=True)
  banner_image = models.ImageField(upload_to='ads/banners/', blank=True, null=True)
  target_url = models.URLField(
      blank=True, help_text='Custom landing page or store link for the ad click.'
  )

  # Scheduling & Budget
  start_date = models.DateTimeField()
  end_date = models.DateTimeField()
  budget = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

  # Status & Tracking Metrics
  status = models.CharField(
      max_length=20,
      choices=Status.choices,
      default=Status.PENDING,
      db_index=True,
  )
  clicks_count = models.PositiveIntegerField(default=0)
  impressions_count = models.PositiveIntegerField(default=0)

  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  class Meta:
    ordering = ['-created_at']
    indexes = [
        models.Index(fields=['status', 'start_date', 'end_date']),
    ]

  def __str__(self):
    return f'{self.title} - {self.store.name} ({self.status})'

  def save(self, *args, **kwargs):
    # Auto-generate a unique slug from the title if not provided
    if not self.slug:
      base = slugify(self.title)[:200] or 'advertisement'
      slug, n = base, 2
      while Advertisement.objects.filter(slug=slug).exclude(pk=self.pk).exists():
        slug = f'{base}-{n}'
        n += 1
      self.slug = slug
    super().save(*args, **kwargs)


class Announcement(models.Model):
  # Foreign Keys linking user and store
  user = models.ForeignKey(
      settings.AUTH_USER_MODEL,
      on_delete=models.CASCADE,
      related_name='announcements',
      help_text='The user who created the announcement.',
  )
  store = models.ForeignKey(
      Store,
      on_delete=models.CASCADE,
      related_name='announcements',
      null=True,
      blank=True,
      help_text='The store associated with this announcement (leave blank for platform-wide).',
  )

  # Content Details
  title = models.CharField(max_length=200)
  slug = models.SlugField(max_length=220, unique=True, blank=True)
  content = models.TextField()
  banner_image = models.ImageField(upload_to='announcements/', blank=True, null=True)

  # Visibility & Scheduling
  is_active = models.BooleanField(default=True)
  start_date = models.DateTimeField(null=True, blank=True, help_text='When the announcement goes live.')
  end_date = models.DateTimeField(null=True, blank=True, help_text='When the announcement expires.')

  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  class Meta:
    ordering = ['-created_at']
    indexes = [
        models.Index(fields=['is_active', 'start_date', 'end_date']),
    ]

  def __str__(self):
    target = self.store.name if self.store else 'Platform-wide'
    return f'{self.title} ({target})'

  def save(self, *args, **kwargs):
    # Auto-generate a unique slug from the title if not provided
    if not self.slug:
      base = slugify(self.title)[:200] or 'announcement'
      slug, n = base, 2
      while Announcement.objects.filter(slug=slug).exclude(pk=self.pk).exists():
        slug = f'{base}-{n}'
        n += 1
      self.slug = slug
    super().save(*args, **kwargs)