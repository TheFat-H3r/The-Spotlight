import re

from django.contrib import messages
from django.contrib.auth import logout, authenticate, login
from django.shortcuts import redirect, render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.views import View

from accounts.models import User
from accounts.utils import redirect_by_role, send_password_reset_email, send_verification_email
from stores.models import Store, unique_slug


class RegisterView(View):
    template_name = 'accounts/register.html'

    def get(self, request):
        if request.user.is_authenticated:
            if request.user.is_email_verified:
                return redirect('core:home')
            return redirect('accounts:resend_verification')
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
                return redirect('store:store-create')

            messages.success(request, "Registration successful! Check your email to activate your account.")
            return redirect('accounts:resend_verification')

        return redirect('core:home')


class VerifyEmailNoticeView(View):
    """Displays the static 'Check Your Inbox' card after registration or redirection."""
    template_name = 'accounts/verify_email.html'

    def get(self, request):
        if request.user.is_authenticated and request.user.is_email_verified:
            return redirect('core:home')

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
    
    template_name = 'accounts/resend_verification.html'

    def get(self, request):
        if request.user.is_authenticated and request.user.is_email_verified:
            return redirect('core:home')

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
        request.session['next_url'] = request.POST.get('next') or request.GET.get('next')
        
        if request.user.is_authenticated:
            if request.user.is_email_verified:
                if request.user.role == "customer":
                    return redirect('core:home')
                elif request.user.role == "vendor":
                    return redirect('shopkeeper:home')
                elif request.user.role == "admin":
                    return redirect('operations:admin-home')
            return redirect('accounts:resend_verification')
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

        return redirect_by_role(user)


class ProfileView(LoginRequiredMixin, View):
    template_name = 'accounts/profile.html'
    login_url = 'accounts:login'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role in ( # type: ignore
            User.Role.VENDOR,
            User.Role.ADMIN,
        ):
            messages.error(request, "This profile page is only accessible to customer accounts.")
            if request.user.role == User.Role.VENDOR: # type: ignore
                return redirect('shopkeeper:dashboard')  # replace with your vendor dashboard URL name
            return redirect('core:home')  # or your admin dashboard URL name

        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        user = request.user
        edit_mode = request.GET.get('edit') == 'true'

        context = {
            'user_obj': user,
            'customer_profile': user,
            'residence_choices': User.Residence.choices,
            'course_choices': User.Course.choices,
            'edit_mode': edit_mode,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        user = request.user

        # 1. Common User Fields
        full_name = request.POST.get('full_name', '').strip()
        phone = request.POST.get('phone', '').strip()
        avatar = request.FILES.get('avatar')

        # 2. Customer Fields
        course = request.POST.get('course', '').strip()
        cohort = request.POST.get('cohort', '').strip().upper()
        residence = request.POST.get('residence', '').strip()
        room_number = request.POST.get('room_number', '').strip().upper()

        error_context = {
            'user_obj': user,
            'customer_profile': user,
            'residence_choices': User.Residence.choices,
            'course_choices': User.Course.choices,
            'edit_mode': True,
            'form_data': request.POST,
        }

        # 3. Validate Common Fields
        if not full_name:
            messages.error(request, "Full name is required.")
            return render(request, self.template_name, error_context)

        if not phone:
            messages.error(request, "Phone number is required.")
            return render(request, self.template_name, error_context)

        # 4. Validate Customer Fields
        if cohort and not re.match(r"^[A-Z]'\d{2}$", cohort):
            messages.error(request, "Cohort must strictly match the format F'25.")
            return render(request, self.template_name, error_context)

        if residence and residence not in User.Residence.values:
            messages.error(request, "Please select a valid campus residence.")
            return render(request, self.template_name, error_context)

        if room_number and not re.match(r"^[A-Z]\d{3}$", room_number):
            messages.error(request, "Room number must strictly match the format S101.")
            return render(request, self.template_name, error_context)

        # 5. Save User Updates
        user.full_name = full_name
        user.phone = phone
        user.course = course
        user.cohort = cohort
        user.residence = residence
        user.room_number = room_number
        if avatar:
            user.avatar = avatar

        user.save()

        messages.success(request, "Your profile has been updated successfully.")
        return redirect('accounts:profile')
class PasswordResetRequestView(View):
    
    template_name = 'accounts/password_reset.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('core:home')
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
    return redirect("accounts:login")

def user_settings(request):

    context = {
        'user':request.user,
    }
    return render(request, 'accounts/user-settings.html', context)