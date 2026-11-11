from django.contrib import messages
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views import View
from .forms import GoogleOnboardingForm
from .models import User, CustomerProfile, VendorApplication
from .utils import redirect_by_role


class RegisterView(View):
    template_name = 'accounts/register.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('marketplace:home')
        return render(request, self.template_name)

    def post(self, request):
        full_name = request.POST.get('full_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        role = request.POST.get('role', User.Role.CUSTOMER).strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        # Pass non-sensitive data back to template to preserve inputs on error
        context = {
            'full_name': full_name,
            'email': email,
            'phone': phone,
            'role': role,
        }

        # 1. Basic Required Fields Check
        if not all([full_name, email, phone, password, confirm_password]):
            messages.error(request, "All fields are required.")
            return render(request, self.template_name, context)

        # 2. Role Restriction Validation
        if role == User.Role.ADMIN or role not in [User.Role.CUSTOMER, User.Role.VENDOR]:
            messages.error(request, "Administrator registration is restricted.")
            return render(request, self.template_name, context)

        # 3. Password Validation Rules
        if len(password) < 8:
            messages.error(request, "Password must be at least 8 characters long.")
            return render(request, self.template_name, context)

        if not any(char.isdigit() for char in password) or not any(char.isalpha() for char in password) or not any(char in "!@#$%^&*()-_=+[]{}|;:'\",.<>?/`~" for char in password):
            messages.error(request, "Password must include a number, letter & symbol.")
            return render(request, self.template_name, context)

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, self.template_name, context)

        # 4. Email Uniqueness Check
        if User.objects.filter(email__iexact=email).exists():
            messages.error(request, "An account with this email address already exists.")
            return render(request, self.template_name, context)

        # 5. User Creation & Saving
        user = User(
            full_name=full_name,
            email=email.lower(),
            phone=phone,
            role=role,
            auth_provider=User.AuthProvider.EMAIL,
        )
        user.set_password(password)
        user.save()

        # Log in user automatically after successful registration
        authenticated_user = authenticate(request, email=email.lower(), password=password)

        if authenticated_user is not None:
            login(request, authenticated_user)

        messages.success(request, "Account created successfully!")

        return redirect('marketplace:home')


class LoginView(View):
    template_name = 'accounts/login.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('marketplace:home')
        return render(request, self.template_name)

    def post(self, request):
        email = (request.POST.get('email') or request.POST.get('username') or '').strip()
        password = request.POST.get('password', '')

        # Build context with entered email to pass back to template
        context = {
            'email': email,
        }

        if not email or not password:
            messages.error(request, "Please enter both email and password.")
            return render(request, self.template_name, context)

        user = authenticate(request, email=email.lower(), password=password)

        if user is None:
            messages.error(request, "Invalid email or password.")
            return render(request, self.template_name, context)

        if not user.is_active:
            messages.error(request, "This account has been deactivated.")
            return render(request, self.template_name, context)

        login(request, user)

        if not request.POST.get('remember_me'):
            request.session.set_expiry(0)

        next_url = request.GET.get('next', 'marketplace:home')
        return redirect(next_url)
    
    
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

def password_reset_view(request):
    # Placeholder for password reset logic
    return render(request, "accounts/password_reset.html")

def logout_view(request):
    logout(request)
    return redirect("users:login")