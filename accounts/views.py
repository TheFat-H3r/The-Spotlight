import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views import View
from urllib3 import request
from .models import User, CustomerProfile, VendorApplication, VendorProfile
from .utils import redirect_by_role, send_password_reset_email, send_verification_email


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

            request.session['unverified_email'] = user.email

            # Redirect VENDOR straight to the vendor application form after signup
            if user.role == User.Role.VENDOR:
                request.session['pending_vendor_id'] = user.pk
                messages.success(request, "Account created! Please complete your vendor application below. Don't forget to verify your email via the link sent to your inbox.")
                return redirect('accounts:vendor_application')

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
        next_url = request.GET.get('next')
        if next_url:
            return redirect(next_url)
        return redirect_by_role(user)

class ProfileView(LoginRequiredMixin, View):
    template_name = 'accounts/profile.html'
    login_url = 'accounts:login'

    def _get_role_data(self, user):
        """Fetches or initializes role-specific profile records safely."""
        customer_profile = None
        vendor_profile = None

        if user.role == User.Role.CUSTOMER:
            customer_profile, _ = CustomerProfile.objects.get_or_create(user=user)
        elif user.role == User.Role.VENDOR:
            default_name = user.full_name or user.email.split('@')[0]
            vendor_profile, _ = VendorProfile.objects.get_or_create(
                user=user,
                defaults={
                    'business_name': default_name,
                    'slug': VendorProfile.generate_unique_slug(default_name),
                    'contact_email': user.email,
                    'contact_phone': user.phone or '',
                }
            )

        return customer_profile, vendor_profile

    def get(self, request):
        user = request.user
        customer_profile, vendor_profile = self._get_role_data(user)
        edit_mode = request.GET.get('edit') == 'true'

        context = {
            'user_obj': user,
            'customer_profile': customer_profile,
            'vendor_profile': vendor_profile,
            'residence_choices': CustomerProfile.Residence.choices,
            'course_choices': CustomerProfile.Course.choices,
            'edit_mode': edit_mode,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        user = request.user
        customer_profile, vendor_profile = self._get_role_data(user)

        # 1. Common User Fields
        full_name = request.POST.get('full_name', '').strip()
        phone = request.POST.get('phone', '').strip()

        # 2. Customer Fields
        course = request.POST.get('course', '').strip()
        cohort = request.POST.get('cohort', '').strip().upper()
        residence = request.POST.get('residence', '').strip()
        room_number = request.POST.get('room_number', '').strip().upper()

        # 3. VendorProfile Fields
        business_name = request.POST.get('business_name', '').strip()
        tagline = request.POST.get('tagline', '').strip()
        description = request.POST.get('description', '').strip()
        contact_email = request.POST.get('contact_email', '').strip()
        contact_phone = request.POST.get('contact_phone', '').strip()
        whatsapp = request.POST.get('whatsapp', '').strip()

        instagram = request.POST.get('instagram', '').strip()
        tiktok = request.POST.get('tiktok', '').strip()
        website = request.POST.get('website', '').strip()

        logo = request.FILES.get('logo')
        banner = request.FILES.get('banner')

        error_context = {
            'user_obj': user,
            'customer_profile': customer_profile,
            'vendor_profile': vendor_profile,
            'residence_choices': CustomerProfile.Residence.choices,
            'edit_mode': True,
            'form_data': request.POST,
        }

        # 4. Validate Common Fields
        if not full_name:
            messages.error(request, "Full name is required.")
            return render(request, self.template_name, error_context)

        if not phone:
            messages.error(request, "Phone number is required.")
            return render(request, self.template_name, error_context)

        # 5. Validate & Save Role-Specific Profile
        if user.role == User.Role.CUSTOMER:
            if cohort and not re.match(r"^[A-Z]'\d{2}$", cohort):
                messages.error(request, "Cohort must strictly match the format F'25.")
                return render(request, self.template_name, error_context)

            if residence and residence not in CustomerProfile.Residence.values:
                messages.error(request, "Please select a valid campus residence.")
                return render(request, self.template_name, error_context)

            if room_number and not re.match(r"^[A-Z]\d{3}$", room_number):
                messages.error(request, "Room number must strictly match the format S101.")
                return render(request, self.template_name, error_context)

            assert customer_profile is not None
            customer_profile.course = course
            customer_profile.cohort = cohort
            customer_profile.residence = residence
            customer_profile.room_number = room_number
            customer_profile.save()

        elif user.role == User.Role.VENDOR:
            if not business_name:
                messages.error(request, "Business name is required for vendors.")
                return render(request, self.template_name, error_context)

            social_links = {}
            if instagram:
                social_links['instagram'] = instagram
            if tiktok:
                social_links['tiktok'] = tiktok
            if website:
                social_links['website'] = website

            assert vendor_profile is not None
            if vendor_profile.business_name != business_name:
                vendor_profile.slug = VendorProfile.generate_unique_slug(business_name)

            vendor_profile.business_name = business_name
            vendor_profile.tagline = tagline
            vendor_profile.description = description
            vendor_profile.contact_email = contact_email or user.email
            vendor_profile.contact_phone = contact_phone or phone
            vendor_profile.whatsapp = whatsapp
            vendor_profile.social_links = social_links

            if logo:
                vendor_profile.logo = logo
            if banner:
                vendor_profile.banner = banner

            vendor_profile.save()

        # 6. Save Base User Updates
        user.full_name = full_name
        user.phone = phone
        user.save(update_fields=['full_name', 'phone'])

        messages.success(request, "Your profile has been updated successfully.")
        return redirect('accounts:profile')


class VendorApplicationView(View):
    template_name = 'accounts/vendor_application.html'

    def _get_applicant(self, request):
        """Returns the authenticated VENDOR user or the newly registered pending vendor from session."""
        if request.user.is_authenticated:
            return request.user if request.user.role == User.Role.VENDOR else None

        pending_id = request.session.get('pending_vendor_id')
        if pending_id:
            return User.objects.filter(pk=pending_id, role=User.Role.VENDOR).first()

        return None

    def get(self, request):
        applicant = self._get_applicant(request)

        if applicant is None:
            if request.user.is_authenticated:
                messages.info(request, "Vendor applications are only for vendor accounts.")
                return redirect('marketplace:home')
            return redirect('accounts:login')

        if hasattr(applicant, 'vendor_profile'):
            return redirect('accounts:profile')

        existing_app = VendorApplication.objects.filter(applicant=applicant).order_by('-id').first()
        reapply = request.GET.get('reapply') == 'true'

        context = {
            'user_obj': applicant,
            'existing_app': existing_app,
            'show_form': existing_app is None or (existing_app.status == 'rejected' and reapply),
        }
        return render(request, self.template_name, context)

    def post(self, request):
        applicant = self._get_applicant(request)

        if applicant is None:
            return redirect('accounts:login')

        existing_app = VendorApplication.objects.filter(applicant=applicant).order_by('-id').first()
        if existing_app and existing_app.status in ['pending', 'approved']:
            messages.info(request, "You already have an active or pending vendor application.")
            return redirect('accounts:vendor_application')

        business_name = request.POST.get('business_name', '').strip()
        business_type = request.POST.get('business_type', '').strip()
        contact_phone = request.POST.get('contact_phone', '').strip() or applicant.phone
        description = request.POST.get('description', '').strip()

        context = {
            'user_obj': applicant,
            'existing_app': existing_app,
            'show_form': True,
            'form_data': request.POST,
        }

        if not all([business_name, business_type, contact_phone, description]):
            messages.error(request, "All fields are required to submit your vendor application.")
            return render(request, self.template_name, context)

        if len(description) < 20:
            messages.error(request, "Please provide a brief description of at least 20 characters.")
            return render(request, self.template_name, context)

        VendorApplication.objects.create(
            applicant=applicant,
            business_name=business_name,
            business_type=business_type,
            contact_phone=contact_phone,
            description=description,
        )

        # Clear temporary registration session key
        request.session.pop('pending_vendor_id', None)

        # If they just registered and haven't verified their email yet, send them to the verify notice page
        if not request.user.is_authenticated and not getattr(applicant, 'is_email_verified', False):
            messages.success(request, "Vendor application submitted! Now check your inbox to verify your email before signing in.")
            return redirect('accounts:verify_email')

        messages.success(request, "Your vendor application has been submitted for review!")
        return redirect('accounts:vendor_application')
    
      
class PasswordResetRequestView(View):
    """Handles 'Forgot Password' email submission."""
    template_name = 'accounts/password_reset.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('marketplace:home')
        return render(request, self.template_name)

    def post(self, request):
        email = (request.POST.get('email') or '').strip().lower()
        context = {'email': email}

        if not email:
            messages.error(request, "Please enter your email address.")
            return render(request, self.template_name, context)

        # 1. Check if an account with this email exists
        user = User.objects.filter(email__iexact=email).first()

        if user is None:
            messages.error(request, "No account found with this email address.")
            return render(request, self.template_name, context)

        # 2. Check if the account is active
        if not user.is_active:
            messages.error(request, "This account has been deactivated.")
            return render(request, self.template_name, context)

        # 3. Check if the account uses Email/Password authentication (not Google OAuth)
        if getattr(user, 'auth_provider', None) != User.AuthProvider.EMAIL:
            messages.error(request, "This account uses Google Sign-In. Please sign in with Google instead.")
            return render(request, self.template_name, context)

        # 4. Generate token and dispatch email via Brevo
        token = user.generate_password_reset_token()
        reset_path = reverse('accounts:password_reset_confirm', kwargs={'token': token})
        reset_url = request.build_absolute_uri(reset_path)

        try:
            send_password_reset_email(
                user_email=user.email,
                user_name=getattr(user, 'full_name', user.email),
                reset_url=reset_url
            )
        except Exception as e:
            print(f"Failed to dispatch password reset email: {e}")
            messages.error(request, "Unable to send reset email right now. Please try again shortly.")
            return render(request, self.template_name, context)

        messages.success(request, "A password reset link has been sent to your email address.")
        return redirect('accounts:login')

class PasswordResetConfirmView(View):
    """Handles setting the new password when user clicks the reset link."""
    template_name = 'accounts/password_reset_confirm.html'

    def get(self, request, token):
        user = User.verify_password_reset_token(token, max_age=900)  # 15 minutes
        if user is None:
            messages.error(request, "The password reset link is invalid or has expired.")
            return redirect('accounts:password_reset')

        return render(request, self.template_name, {'token': token})

    def post(self, request, token):
        user = User.verify_password_reset_token(token, max_age=900)
        if user is None:
            messages.error(request, "The password reset link is invalid or has expired.")
            return redirect('accounts:password_reset')

        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')
        context = {'token': token}

        if not password or not confirm_password:
            messages.error(request, "Both password fields are required.")
            return render(request, self.template_name, context)

        if len(password) < 8:
            messages.error(request, "Password must be at least 8 characters long.")
            return render(request, self.template_name, context)

        if (
            not any(char.isdigit() for char in password)
            or not any(char.isalpha() for char in password)
            or not any(char in "!@#$%^&*()-_=+[]{}|;:'\",.<>?/`~" for char in password)
        ):
            messages.error(request, "Password must include a number, letter & symbol.")
            return render(request, self.template_name, context)

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, self.template_name, context)

        user.set_password(password)
        user.save(update_fields=['password'])

        messages.success(request, "Your password has been reset! You can now sign in with your new password.")
        return redirect('accounts:login')

def logout_view(request):
    logout(request)
    return redirect("users:login")