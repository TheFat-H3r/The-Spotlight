from datetime import datetime, timedelta

from django import forms
from django.utils import timezone
from django.utils.text import slugify
from marketing.models import Advertisement, Announcement
from stores.models import BusinessType, Category, Product, Service, Store
from transactions.models import AvailabilitySlot


DAYS_OF_WEEK = [
    ("mon", "Monday"),
    ("tue", "Tuesday"),
    ("wed", "Wednesday"),
    ("thu", "Thursday"),
    ("fri", "Friday"),
    ("sat", "Saturday"),
    ("sun", "Sunday"),
]


class StoreProfileForm(forms.ModelForm):
    """Used for creating a vendor's single store or editing its public identity."""

    categories = forms.ModelMultipleChoiceField(
        queryset=Category.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
    )

    class Meta:
        model = Store
        fields = [
            "name",
            "business_type",
            "tagline",
            "description",
            "logo",
            "banner",
            "categories",
            "contact_phone",
            "contact_email",
            "whatsapp",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Nova Tech Studio"}),
            "business_type": forms.Select(attrs={"class": "form-select"}),
            "tagline": forms.TextInput(attrs={"class": "form-control", "placeholder": "Short catchy summary (max 160 chars)"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 4, "placeholder": "Tell customers about your business..."}),
            "logo": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "banner": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "contact_phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "+230 5XXX XXXX"}),
            "contact_email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "store@example.com"}),
            "whatsapp": forms.TextInput(attrs={"class": "form-control", "placeholder": "+230 5XXX XXXX"}),
        }

    def __init__(self, *args, **kwargs):
        self.owner = kwargs.pop("owner", None)
        super().__init__(*args, **kwargs)
        self.fields["business_type"].queryset = BusinessType.objects.all() # type: ignore
        # Lock business_type once the store already exists so existing orders/bookings don't mismatch
        if self.instance and self.instance.pk:
            self.fields["business_type"].disabled = True
            self.fields["business_type"].help_text = (
                "Business type is locked after creation. Contact support via Business Verification to request a change."
            )

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        qs = Store.objects.filter(owner=self.owner, name__iexact=name)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("You already have a store with this name.")
        return name


class StoreSettingsForm(forms.ModelForm):
    """
    Operational settings: social links, structured opening hours, fulfillment (products),
    or appointment location & booking availability (services).
    """

    instagram = forms.URLField(
        required=False,
        widget=forms.URLInput(attrs={"class": "form-control", "placeholder": "https://instagram.com/yourhandle"}),
    )
    facebook = forms.URLField(
        required=False,
        widget=forms.URLInput(attrs={"class": "form-control", "placeholder": "https://facebook.com/yourpage"}),
    )
    tiktok = forms.URLField(
        required=False,
        widget=forms.URLInput(attrs={"class": "form-control", "placeholder": "https://tiktok.com/@yourhandle"}),
    )
    website = forms.URLField(
        required=False,
        widget=forms.URLInput(attrs={"class": "form-control", "placeholder": "https://yourwebsite.com"}),
    )

    class Meta:
        model = Store
        fields = [
            "pickup_location",
            "offers_delivery",
            "is_accepting_orders",
        ]
        widgets = {
            "pickup_location": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g. ALCHE Campus — Student Hub / Room S101"}
            ),
            "offers_delivery": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_accepting_orders": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        social = (self.instance.social_links or {}) if self.instance else {}
        self.fields["instagram"].initial = social.get("instagram", "")
        self.fields["facebook"].initial = social.get("facebook", "")
        self.fields["tiktok"].initial = social.get("tiktok", "")
        self.fields["website"].initial = social.get("website", "")

        # Tailor labels/visibility to store type
        if self.instance and self.instance.pk:
            if self.instance.accepts_bookings and not self.instance.accepts_orders:
                self.fields["pickup_location"].label = "Service / Appointment Location"
                self.fields["pickup_location"].help_text = "Where clients meet you or receive the service."
                self.fields["is_accepting_orders"].label = "Accepting New Bookings"
                self.fields["is_accepting_orders"].help_text = "Switch off to pause new appointment requests during breaks."
                self.fields.pop("offers_delivery", None)
            elif self.instance.accepts_bookings and self.instance.accepts_orders:
                self.fields["pickup_location"].label = "Pickup & Service Location"
                self.fields["is_accepting_orders"].label = "Accepting New Orders & Bookings"

    def save(self, commit=True):
        store = super().save(commit=False)
        store.social_links = {
            key: val.strip()
            for key, val in {
                "instagram": self.cleaned_data.get("instagram", ""),
                "facebook": self.cleaned_data.get("facebook", ""),
                "tiktok": self.cleaned_data.get("tiktok", ""),
                "website": self.cleaned_data.get("website", ""),
            }.items()
            if val and val.strip()
        }
        if commit:
            store.save()
        return store


class VerificationComplaintForm(forms.Form):
    """Allows a vendor to submit a verification appeal or status inquiry to admins."""

    SUBJECT_CHOICES = [
        ("verification_review", "Request Verification / Activation Review"),
        ("suspension_appeal", "Appeal Store Suspension"),
        ("business_type_change", "Request Business Type Change"),
        ("other", "Other Moderation Inquiry"),
    ]

    subject = forms.ChoiceField(
        choices=SUBJECT_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    message = forms.CharField(
        min_length=15,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Explain your request or provide details for the admin team...",
            }
        ),
    )

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "name",
            "category",
            "price",
            "stock",
            "image",
            "description",
            "is_available",
            "is_featured",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g. Custom ALCHE Hoodie"}
            ),
            "category": forms.Select(attrs={"class": "form-select"}),
            "price": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "0", "placeholder": "0.00"}
            ),
            "stock": forms.NumberInput(
                attrs={"class": "form-control", "min": "0", "placeholder": "0"}
            ),
            "image": forms.ClearableFileInput(
                attrs={"class": "form-control", "accept": "image/*"}
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Describe materials, sizes, colors, or usage details...",
                }
            ),
            "is_available": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_featured": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        self.store = kwargs.pop("store", None)
        super().__init__(*args, **kwargs)

        # Scope category choices to the store's selected categories if configured, otherwise all categories
        if self.store and self.store.categories.exists():
            self.fields["category"].queryset = self.store.categories.all() # type: ignore
        else:
            self.fields["category"].queryset = Category.objects.all() # type: ignore
        self.fields["category"].empty_label = "— Uncategorized —" # type: ignore

    def clean_price(self):
        price = self.cleaned_data.get("price")
        if price is None:
            return 0
        if price < 0:
            raise forms.ValidationError("Price cannot be negative.")
        return price

    def save(self, commit=True):
        product = super().save(commit=False)
        if self.store:
            product.store = self.store

        # Generate a unique slug from name if creating or if slug is empty
        if not product.slug:
            base_slug = slugify(product.name)[:240] or "product"
            slug = base_slug
            counter = 2
            qs = Product.objects.all()
            if product.pk:
                qs = qs.exclude(pk=product.pk)
            while qs.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            product.slug = slug

        if commit:
            product.save()
        return product


class ServiceForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = [
            "name",
            "category",
            "starting_price",
            "image",
            "description",
            "is_available",
            "is_featured",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g. Box Braids / 1-on-1 Python Tutoring"}
            ),
            "category": forms.Select(attrs={"class": "form-select"}),
            "starting_price": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "0", "placeholder": "0.00"}
            ),
            "image": forms.ClearableFileInput(
                attrs={"class": "form-control", "accept": "image/*"}
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Describe what's included, duration, preparation tips, etc...",
                }
            ),
            "is_available": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_featured": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        self.store = kwargs.pop("store", None)
        super().__init__(*args, **kwargs)

        if self.store and self.store.categories.exists():
            self.fields["category"].queryset = self.store.categories.all() # type: ignore
        else:
            self.fields["category"].queryset = Category.objects.all() # type: ignore
        self.fields["category"].empty_label = "— Uncategorized —" # type: ignore

    def clean_starting_price(self):
        price = self.cleaned_data.get("starting_price")
        if price is None:
            return 0
        if price < 0:
            raise forms.ValidationError("Starting price cannot be negative.")
        return price

    def save(self, commit=True):
        service = super().save(commit=False)
        if self.store:
            service.store = self.store

        if not service.slug:
            base_slug = slugify(service.name)[:250] or "service"
            slug = base_slug
            counter = 2
            qs = Service.objects.all()
            if service.pk:
                qs = qs.exclude(pk=service.pk)
            while qs.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            service.slug = slug

        if commit:
            service.save()
        return service


class AvailabilitySlotForm(forms.ModelForm):
    class Meta:
        model = AvailabilitySlot
        fields = ["service", "start_at", "end_at", "capacity", "is_active"]
        widgets = {
            "service": forms.Select(attrs={"class": "form-select"}),
            "start_at": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "end_at": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "capacity": forms.NumberInput(
                attrs={"class": "form-control", "min": "1", "placeholder": "Default: 1"}
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        self.store = kwargs.pop("store", None)
        super().__init__(*args, **kwargs)
        self.fields["start_at"].input_formats = ["%Y-%m-%dT%H:%M"] # type: ignore
        self.fields["end_at"].input_formats = ["%Y-%m-%dT%H:%M"] # type: ignore
        if self.store:
            self.fields["service"].queryset = Service.objects.filter(store=self.store).order_by("name") # type: ignore


class BulkSlotGeneratorForm(forms.Form):
    """Generates multiple consecutive appointment slots across a date range."""

    service = forms.ModelChoiceField(
        queryset=Service.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    start_date = forms.DateField(
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"})
    )
    end_date = forms.DateField(
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"})
    )
    day_start_time = forms.TimeField(
        initial="09:00",
        widget=forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
    )
    day_end_time = forms.TimeField(
        initial="17:00",
        widget=forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
    )
    slot_duration_minutes = forms.IntegerField(
        min_value=15,
        max_value=720,
        initial=60,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": "15", "step": "15"}),
    )
    break_minutes = forms.IntegerField(
        min_value=0,
        max_value=240,
        initial=0,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": "0", "step": "5"}),
    )
    capacity = forms.IntegerField(
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": "1", "placeholder": "Default: 1"}),
    )

    def __init__(self, *args, **kwargs):
        self.store = kwargs.pop("store", None)
        super().__init__(*args, **kwargs)
        if self.store:
            self.fields["service"].queryset = Service.objects.filter(store=self.store).order_by("name") # type: ignore

    def clean(self):
        cleaned = super().clean()
        assert cleaned is not None
        start_date = cleaned.get("start_date")
        end_date = cleaned.get("end_date")
        start_time = cleaned.get("day_start_time")
        end_time = cleaned.get("day_end_time")

        if start_date and end_date:
            if end_date < start_date:
                self.add_error("end_date", "End date cannot be earlier than start date.")
            elif (end_date - start_date).days > 31:
                self.add_error("end_date", "Generate up to 31 days at a time.")

        if start_time and end_time and end_time <= start_time:
            self.add_error("day_end_time", "Daily end time must be after daily start time.")

        return cleaned

    def build_slots(self) -> list[AvailabilitySlot]:
        service = self.cleaned_data["service"]
        start_date = self.cleaned_data["start_date"]
        end_date = self.cleaned_data["end_date"]
        day_start = self.cleaned_data["day_start_time"]
        day_end = self.cleaned_data["day_end_time"]
        duration = timedelta(minutes=self.cleaned_data["slot_duration_minutes"])
        buffer = timedelta(minutes=self.cleaned_data["break_minutes"])
        capacity = self.cleaned_data.get("capacity")

        tz = timezone.get_current_timezone()
        now = timezone.now()
        created_candidates: list[AvailabilitySlot] = []

        current_day = start_date
        while current_day <= end_date:
            cursor = timezone.make_aware(datetime.combine(current_day, day_start), tz)
            day_limit = timezone.make_aware(datetime.combine(current_day, day_end), tz)

            while cursor + duration <= day_limit:
                slot_end = cursor + duration
                if cursor > now:
                    overlaps = AvailabilitySlot.objects.filter(
                        service=service,
                        start_at__lt=slot_end,
                        end_at__gt=cursor,
                    ).exists()
                    if not overlaps:
                        created_candidates.append(
                            AvailabilitySlot(
                                service=service,
                                start_at=cursor,
                                end_at=slot_end,
                                capacity=capacity,
                                is_active=True,
                            )
                        )
                cursor = slot_end + buffer
            current_day += timedelta(days=1)

        return created_candidates


class AdvertisementForm(forms.ModelForm):
    class Meta:
        model = Advertisement
        fields = [
            "title",
            "description",
            "banner_image",
            "target_url",
            "start_date",
            "end_date",
            "budget",
            "is_active",
        ]
        widgets = {
            "title": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g. Weekend Fresh Bake Sale — 20% Off"}
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Short promotional copy displayed with your banner...",
                }
            ),
            "banner_image": forms.ClearableFileInput(
                attrs={"class": "form-control", "accept": "image/*"}
            ),
            "target_url": forms.URLInput(
                attrs={"class": "form-control", "placeholder": "https://... (optional; defaults to your store)"}
            ),
            "start_date": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "end_date": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "budget": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "0", "placeholder": "0.00"}
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["start_date"].input_formats = ["%Y-%m-%dT%H:%M"] # type: ignore
        self.fields["end_date"].input_formats = ["%Y-%m-%dT%H:%M"] # type: ignore

    def clean(self):
        cleaned = super().clean()
        assert cleaned is not None
        start_date = cleaned.get("start_date")
        end_date = cleaned.get("end_date")
        budget = cleaned.get("budget")

        if start_date and end_date and end_date <= start_date:
            self.add_error("end_date", "End date & time must be after the start date & time.")

        if budget is not None and budget < 0:
            self.add_error("budget", "Budget cannot be negative.")

        return cleaned


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = [
            "title",
            "content",
            "banner_image",
            "start_date",
            "end_date",
            "is_active",
        ]
        widgets = {
            "title": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g. Extended Friday Hours or New Menu Launch"}
            ),
            "content": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Write your announcement details for customers...",
                }
            ),
            "banner_image": forms.ClearableFileInput(
                attrs={"class": "form-control", "accept": "image/*"}
            ),
            "start_date": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "end_date": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["start_date"].input_formats = ["%Y-%m-%dT%H:%M"] # type: ignore
        self.fields["end_date"].input_formats = ["%Y-%m-%dT%H:%M"] # type: ignore

    def clean(self):
        cleaned = super().clean()
        assert cleaned is not None
        start_date = cleaned.get("start_date")
        end_date = cleaned.get("end_date")
        if start_date and end_date and end_date <= start_date:
            self.add_error("end_date", "Expiration date & time must be after the start date & time.")
        return cleaned