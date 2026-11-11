from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.views import View
from .forms import UserRegistrationForm, UserLoginForm, GoogleOnboardingForm
from .models import User, CustomerProfile, VendorApplication
from .utils import redirect_by_role


class RegisterView(View):
    template_name = "accounts/register.html"

    def get(self, request):
        if request.user.is_authenticated:
            return redirect_by_role(request.user)
        form = UserRegistrationForm()
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            return redirect_by_role(user)
        return render(request, self.template_name, {"form": form})


class LoginView(View):
    template_name = "accounts/login.html"

    def get(self, request):
        if request.user.is_authenticated:
            return redirect_by_role(request.user)
        form = UserLoginForm()
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = UserLoginForm(request.POST)
        if form.is_valid():
            user = form.cleaned_data["user"]
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            return redirect_by_role(user)
        return render(request, self.template_name, {"form": form})

@login_required
def google_onboarding_view(request):
    user = request.user
    
    # If user already completed onboarding or isn't a google user without profile, skip
    if user.role == User.Role.CUSTOMER and hasattr(user, "customer_profile") and user.customer_profile.department:
        return redirect_by_role(user)

    if request.method == "POST":
        form = GoogleOnboardingForm(request.POST)
        if form.is_valid():
            role = form.cleaned_data["role"]
            user.phone = form.cleaned_data["phone"]
            user.role = role
            user.save()

            if role == User.Role.CUSTOMER:
                CustomerProfile.objects.update_or_create(
                    user=user,
                    defaults={
                        "department": form.cleaned_data["department"],
                        "year_of_study": form.cleaned_data["year_of_study"],
                        "campus_location": form.cleaned_data["campus_location"],
                    }
                )
            elif role == User.Role.VENDOR:
                VendorApplication.objects.create(
                    applicant=user,
                    business_name=form.cleaned_data["business_name"],
                    business_type=form.cleaned_data["business_type"],
                    description=form.cleaned_data["description"],
                    contact_phone=user.phone,
                )
            return redirect_by_role(user)
    else:
        form = GoogleOnboardingForm(initial={"phone": user.phone})

    return render(request, "accounts/google_onboarding.html", {"form": form})

def logout_view(request):
    logout(request)
    return redirect("users:login")