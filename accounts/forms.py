# accounts/forms.py
from django import forms
from django.contrib.auth import authenticate
from .models import User, VendorApplication


class UserRegistrationForm(forms.ModelForm):
    # Restrict role choices to Customer and Vendor only (Exclude ADMIN)
    ROLE_CHOICES = [
        (User.Role.CUSTOMER, "Customer"),
        (User.Role.VENDOR, "Vendor"),
    ]

    role = forms.ChoiceField(
        choices=ROLE_CHOICES,
        #default=User.Role.CUSTOMER, # type: ignore
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "At least 8 characters"}),
        min_length=8,
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Repeat your password"})
    )

    class Meta:
        model = User
        fields = ["full_name", "email", "phone", "role"]
        widgets = {
            "full_name": forms.TextInput(attrs={"placeholder": "Jane Doe"}),
            "email": forms.EmailInput(attrs={"placeholder": "jane@example.com"}),
            "phone": forms.TextInput(attrs={"placeholder": "+1234567890"}),
        }

    def clean_role(self):
        role = self.cleaned_data.get("role")
        if role == User.Role.ADMIN:
            raise forms.ValidationError("Administrator registration is restricted.")
        return role

    def clean(self):
        cleaned_data = super().clean()
        assert cleaned_data is not None
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password and confirm_password and password != confirm_password:
            self.add_error("confirm_password", "Passwords do not match.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        user.auth_provider = User.AuthProvider.EMAIL
        if commit:
            user.save()
        return user

class UserLoginForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"placeholder": "your.email@example.com"})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "••••••••"})
    )

    def clean(self):
        cleaned_data = super().clean()
        assert cleaned_data is not None
        email = cleaned_data.get("email")
        password = cleaned_data.get("password")

        if email and password:
            user = authenticate(email=email.lower(), password=password)
            if not user:
                raise forms.ValidationError("Invalid email or password.")
            if not user.is_active:
                raise forms.ValidationError("This account has been deactivated.")
            cleaned_data["user"] = user # type: ignore
        return cleaned_data


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