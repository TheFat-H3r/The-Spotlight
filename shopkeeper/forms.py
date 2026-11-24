from django import forms
from stores.models import BusinessType, Category, Store


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