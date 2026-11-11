# accounts/forms.py
from django import forms
from django.contrib.auth import authenticate
from .models import User, VendorApplication

class GoogleOnboardingForm(forms.Form):
    ROLE_CHOICES = [
        (User.Role.CUSTOMER, "Customer"),
        (User.Role.VENDOR, "Vendor (Sells Products/Services)"),
    ]
    
    role = forms.ChoiceField(choices=ROLE_CHOICES, widget=forms.RadioSelect(attrs={"class": "form-check-input"}))
    phone = forms.CharField(max_length=16, required=False, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "+1234567890"}))
    
    # Customer specific fields
    department = forms.CharField(max_length=100, required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    year_of_study = forms.IntegerField(required=False, widget=forms.NumberInput(attrs={"class": "form-control"}))
    campus_location = forms.CharField(max_length=120, required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    
    # Vendor specific fields
    business_name = forms.CharField(max_length=150, required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    business_type = forms.ChoiceField(choices=VendorApplication.BusinessType.choices, required=False, widget=forms.Select(attrs={"class": "form-control"}))
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}))

    def clean(self):
        cleaned_data = super().clean()
        assert cleaned_data is not None
        role = cleaned_data.get("role")
        
        if role == User.Role.VENDOR:
            if not cleaned_data.get("business_name"):
                self.add_error("business_name", "Business name is required for vendors.")
            if not cleaned_data.get("description"):
                self.add_error("description", "Description is required for vendors.")
        return cleaned_data