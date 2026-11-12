from django.conf import settings
from django.contrib import messages
from django.urls import reverse
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views import View
from .forms import GoogleOnboardingForm
from .models import User, CustomerProfile, VendorApplication
from .utils import redirect_by_role, send_verification_email


class RegisterView(View):
    template_name = 'accounts/register.html'

    def get(self, request):
        if request.user.is_authenticated:
            if request.user.is_email_verified:
                return redirect('marketplace:home')
            return redirect('accounts:verify_email')
        return render(request, self.template_name)

    def post(self, request):
        full_name = request.POST.get('full_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        role = request.POST.get('role', User.Role.CUSTOMER).strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        context = {
            'full_name': full_name,
            'email': email,
            'phone': phone,
            'role': role,
        }

        if not all([full_name, email, phone, password, confirm_password]):
            messages.error(request, "All fields are required.")
            return render(request, self.template_name, context)

        if role == User.Role.ADMIN or role not in [User.Role.CUSTOMER, User.Role.VENDOR]:
            messages.error(request, "Administrator registration is restricted.")
            return render(request, self.template_name, context)

        if len(password) < 8:
            messages.error(request, "Password must be at least 8 characters long.")
            return render(request, self.template_name, context)

        if not any(char.isdigit() for char in password) or not any(char.isalpha() for char in password) or not any(char in "!@#$%^&*()-_=+[]{}|;:'\",.<>?/`~" for char in password):
            messages.error(request, "Password must include a number, letter & symbol.")
            return render(request, self.template_name, context)

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, self.template_name, context)

        if User.objects.filter(email__iexact=email).exists():
            messages.error(request, "An account with this email address already exists.")
            return render(request, self.template_name, context)

        user = User(
            full_name=full_name,
            email=email.lower(),
            phone=phone,
            role=role,
            auth_provider=User.AuthProvider.EMAIL,
            is_email_verified=False,
        )
        user.set_password(password)
        user.save()

        # Send Email Verification Link via Brevo API
        if user.auth_provider == User.AuthProvider.EMAIL:
            token = user.generate_email_verification_token()
            verification_path = reverse('accounts:verify_email_confirm', kwargs={'token': token})
            verification_url = request.build_absolute_uri(verification_path)

            send_verification_email(
                user_email=user.email,
                user_name=user.full_name,
                verification_url=verification_url
            )

            # Save unverified email to session so verify_email page knows which email to display
            request.session['unverified_email'] = user.email
            messages.success(request, "Registration successful! Check your email to activate your account.")
            return redirect('accounts:verify_email')

        return redirect('marketplace:home')


class VerifyEmailNoticeView(View):
    """Displays the static 'Check Your Inbox' card after registration or redirection."""
    template_name = 'accounts/verify_email.html'

    def get(self, request):
        if request.user.is_authenticated and request.user.is_email_verified:
            return redirect('marketplace:home')

        # Obtain email from logged in user or temporary session key
        email = request.user.email if request.user.is_authenticated else request.session.get('unverified_email', '')
        return render(request, self.template_name, {'email': email})


class VerifyEmailConfirmView(View):
    """Handles verification token clicks from email."""
    def get(self, request, token):
        user = User.verify_email_token(token, max_age=600)  # type: ignore

        if user is None:
            messages.error(request, "The verification link is invalid or has expired.")
            return redirect('accounts:resend_verification')

        if not getattr(user, 'is_email_verified', False):
            user.is_email_verified = True
            user.save(update_fields=['is_email_verified'])
            messages.success(request, "Your email has been verified! You can now sign in.")
        else:
            messages.info(request, "Your email is already verified.")

        request.session.pop('unverified_email', None)
        return redirect('accounts:login')


class ResendVerificationEmailView(View):
    """Dedicated form page for users to enter their email and request a new link."""
    template_name = 'accounts/resend_verification.html'

    def get(self, request):
        if request.user.is_authenticated and request.user.is_email_verified:
            return redirect('marketplace:home')

        email = request.user.email if request.user.is_authenticated else request.session.get('unverified_email', '')
        return render(request, self.template_name, {'email': email})

    def post(self, request):
        email = (request.POST.get('email') or '').strip().lower()
        context = {'email': email}

        if not email:
            messages.error(request, "Please enter your email address.")
            return render(request, self.template_name, context)

        user = User.objects.filter(email__iexact=email).first()
        success_message = "If an account associated with this email exists and requires verification, a new link has been sent."

        if user is None:
            messages.success(request, success_message)
            return redirect('accounts:login')

        is_email_provider = getattr(user, 'auth_provider', None) == getattr(User, 'AuthProvider', None).EMAIL  # type: ignore
        is_unverified = not getattr(user, 'is_email_verified', False)

        if is_email_provider and is_unverified:
            token = user.generate_email_verification_token()  # type: ignore
            verification_path = reverse('accounts:verify_email_confirm', kwargs={'token': token})
            verification_url = request.build_absolute_uri(verification_path)

            send_verification_email(
                user_email=user.email,
                user_name=getattr(user, 'full_name', user.email),
                verification_url=verification_url
            )

        messages.success(request, success_message)
        return redirect('accounts:login')


class LoginView(View):
    template_name = 'accounts/login.html'

    def get(self, request):
        if request.user.is_authenticated:
            if request.user.is_email_verified:
                return redirect('marketplace:home')
            return redirect('accounts:verify_email')
        return render(request, self.template_name)

    def post(self, request):
        email = (request.POST.get('email') or request.POST.get('username') or '').strip()
        password = request.POST.get('password', '')

        context = {'email': email}

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

        # Unverified Check -> Lock login and send user to resend form page
        if getattr(user, 'auth_provider', None) == getattr(User, 'AuthProvider', None).EMAIL:  # type: ignore
            if not getattr(user, 'is_email_verified', False):
                request.session['unverified_email'] = user.email # type: ignore
                messages.warning(request, "Your email is not verified yet. Please request a new link below.")
                return redirect('accounts:resend_verification')

        if not request.POST.get('remember_me'):
            request.session.set_expiry(0)

        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
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