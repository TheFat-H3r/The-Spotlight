import json
import logging
import re
import uuid
from collections import defaultdict
from decimal import Decimal
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives, send_mail
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F
from django.db.models.deletion import ProtectedError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import strip_tags
from django.views import View
from django.views.decorators.http import require_POST
from accounts.models import User
from accounts.utils import redirect_by_role, send_password_reset_email, send_verification_email
from marketing.models import Advertisement, Announcement
from stores.models import Category, Product, Review, Service, Store
from transactions.models import AvailabilitySlot, Booking, Cart, CartItem, Order, OrderItem, OrderStatusHistory, VendorNotification


class RegisterView(View):
    template_name = 'core/register.html'

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
            verification_path = reverse('accounts:resend_verification', kwargs={'token': token})
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
    template_name = 'core/login.html'

    def get(self, request):
        if request.user.is_authenticated:
            if request.user.is_email_verified:
                if request.user.role == "customer":
                    return redirect('core:home')
                elif request.user.role == "vendor":
                    return redirect('shopkeeper:home')
                elif request.user.role == "admin":
                    return redirect('operations:home')
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
        next_url = request.GET.get('next')
        if next_url:
            return redirect(next_url)
        return redirect_by_role(user)


class ProfileView(LoginRequiredMixin, View):
    template_name = 'core/profile.html'
    login_url = 'core:login'

    def _get_role_data(self, user):
        
        customer_profile = None
        vendor_profile = None

        if user.role == User.Role.CUSTOMER:
            customer_profile = user

        if user.role == User.Role.VENDOR:
            default_name = user.full_name or user.email.split('@')[0]
            vendor_profile, _ = Store.objects.get_or_create(
                owner=user,
                defaults={
                    'name': default_name,
                    'slug': Store.generate_unique_slug(default_name), # type: ignore
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
            'residence_choices': User.Residence.choices,
            'course_choices': User.Course.choices,
            'edit_mode': edit_mode,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        user = request.user
        customer_profile, vendor_profile = self._get_role_data(user)

        # 1. Common User Fields
        full_name = request.POST.get('full_name', '').strip()
        phone = request.POST.get('phone', '').strip()
        avatar = request.FILES.get('avatar')

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
            'residence_choices': User.Residence.choices,
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

            if residence and residence not in User.Residence.values:
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
            if Store.name != business_name:
                vendor_profile.slug = Store.generate_unique_slug(business_name) # type: ignore

            vendor_profile.name = business_name
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
        if avatar:
            user.avatar = avatar
        user.save(update_fields=['full_name', 'phone', 'avatar'])

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


# --- Main & Static Pages ---
def home(request):
    products = Product.objects.filter(is_available=True).select_related("store", "store__business_type", "category").order_by("-is_featured", "-created_at")
    services = Service.objects.filter(is_available=True).select_related("store", "store__business_type", "category").order_by("-is_featured", "-created_at")
    featured_ads = (Advertisement.objects.filter(is_active=True, status="active").select_related("store").order_by("-created_at")[:4])
    announcements = (Announcement.objects.filter(is_active=True).order_by("-created_at")[:4])
    featured_reviews = (Review.objects.filter(status="published").select_related("author", "store").order_by("-overall_rating", "-created_at")[:6])
    active_ads = Advertisement.objects.filter(is_active=True, status="active").order_by("-created_at")
    featured_stores = (Store.objects.filter(status="active", is_featured=True).select_related("business_type").order_by("-rating_average", "name"))
    categories = Category.objects.all()
    flash_sales = Product.objects.filter(is_available=True, is_featured=True)[:4]
    
    context = {
        # "active_ads": active_ads, #Don't disclose by now
        "featured_stores": featured_stores[:12],
        "featured_products": Product.objects.filter(is_available=True, is_featured=True),
        "all_products": products,
        "all_services": services,
        "featured_services": Service.objects.filter(is_available=True, is_featured=True)[:4],
        "featured_ads": featured_ads,
        "active_ads": active_ads,
        "announcements": announcements,
        "featured_reviews": featured_reviews,
        "categories": categories,
        "flash_sales": flash_sales
    }
    print(products)
    return render(request, 'core/home.html', context)

def about(request):
    return render(request, 'core/about.html')

def contact(request):
    return render(request, 'core/contact.html')

def faq(request):
    return render(request, 'core/faq.html')

def report(request, slug, store):
    return render(request, 'core/report.html')


def privacy(request):
    return render(request, 'core/privacy.html')

def terms(request):
    return render(request, 'core/terms.html')

# --- Authentication & User Account ---
def login_view(request):
    return render(request, 'core/login.html')

def create_account(request):
    return render(request, 'core/create-account.html')

def user_profile(request):
    return render(request, 'core/user-profile.html')

def become_vendor(request):
    return render(request, 'core/become-vendor.html')

# --- Catalog: Products, Services & Stores ---
def product_list(request):
    # Get all available products
    products = (
        Product.objects
        .filter(is_available=True)
        .select_related("category", "store")
        .order_by("-is_featured", "-created_at")
    )

    # Get unique categories belonging to available products
    categories = (
        Product.objects
        .filter(is_available=True, category__isnull=False)
        .values("category_id", "category__name")
        .order_by("category__name")
        .distinct()
    )

    # Filter products by category if selected
    category_id = request.GET.get("category")

    if category_id:
        products = products.filter(category_id=category_id)

    # Pagination: 12 products per page
    paginator = Paginator(products, 12)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "products": page_obj,
        "page_obj": page_obj,
        "categories": categories,
        "total_products": paginator.count,
        "selected_category": category_id,
    }

    return render(request, "core/product_list.html", context)

def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.select_related("category", "store"),
        slug=slug,
        is_available=True,
    )

    related_services = Service.objects.none()

    if product.category_id:
        related_services = (
            Service.objects
            .filter(
                category_id=product.category_id,
                is_available=True,
            )
            .exclude(pk=None)
            .select_related("store", "category")
            .order_by("-is_featured", "-created_at")[:4]
        )

    context = {
        "product": product,
        "related_services": related_services,
    }

    return render(request, "core/product_detail.html", context)

def service_list(request):
    services = (
        Service.objects
        .filter(is_available=True)
        .select_related("category", "store")
        .order_by("-is_featured", "-created_at")
    )

    categories = (
        Service.objects
        .filter(is_available=True, category__isnull=False)
        .values("category_id", "category__name")
        .order_by("category__name")
        .distinct()
    )

    # Category filtering
    category_id = request.GET.get("category")

    if category_id:
        services = services.filter(category_id=category_id)

    # Pagination
    paginator = Paginator(services, 12)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "services": page_obj,
        "page_obj": page_obj,
        "categories": categories,
        "total_services": paginator.count,
        "selected_category": category_id,
    }

    return render(request, "core/service_list.html", context)

def service_detail(request, slug):
    service = get_object_or_404(
            Service.objects.select_related("category", "store"),
            slug=slug,
            is_available=True,
        )
    
    related_services = Service.objects.none()
    
    if service.category_id:
        related_services = (
                Service.objects
                .filter(
                    category_id=service.category_id,
                    is_available=True,
                )
                .exclude(pk=None)
                .select_related("store", "category")
                .order_by("-is_featured", "-created_at")[:4]
            )
    
    context = {
            "service": service,
            "related_services": related_services,
        }
    
    return render(request, 'core/service_detail.html', context)

def category_detail(request, slug):
    return render(request, 'core/category_detail.html', {'category_slug': slug})

def store_list(request):
    stores = Store.objects.filter(status="active")
    
    context = {
        "stores": stores,
    }
    
    return render(request, 'core/store_list.html', context)


def store_detail(request, slug):
    store = get_object_or_404(
        Store.objects.select_related("business_type"),
        slug=slug
    )

    store_type = store.business_type.store_type

    products = Product.objects.none()
    services = Service.objects.none()

    if store_type in ["products", "both"]:
        products = Product.objects.filter(
            store=store,
            is_available=True
        ).select_related("category").order_by(
            "-is_featured", "-created_at"
        )

    if store_type in ["services", "both"]:
        services = Service.objects.filter(
            store=store,
            is_available=True
        ).select_related("category").order_by(
            "-is_featured", "-created_at"
        )

    # Collect unique categories from this store's products and services.
    categories = {}

    for category in products.values(
        "category_id", "category__name"
    ).distinct():
        if category["category_id"]:
            categories[category["category_id"]] = {
                "id": category["category_id"],
                "name": category["category__name"],
            }

    for category in services.values(
        "category_id", "category__name"
    ).distinct():
        if category["category_id"]:
            categories[category["category_id"]] = {
                "id": category["category_id"],
                "name": category["category__name"],
            }

    context = {
        "store": store,
        "products": products,
        "services": services,
        "categories": list(categories.values()),
        "total_items": products.count() + services.count(),
    }

    return render(request, "core/store_detail.html", context)

def flash_sale(request):
    return render(request, 'core/flash-sale.html')

# --- Shopping & Orders ---
@login_required
def cart_detail(request): # type: ignore
    cart, _ = Cart.objects.get_or_create(customer=request.user)

    items = cart.items.select_related( # type: ignore
        "product",
        "product__store",
        "product__category",
    )

    context = {
        "cart": cart,
        "items": items,
        "total_items": cart.total_items,
        "subtotal": cart.subtotal,
    }

    return render(request, "core/cart.html", context)


@login_required
@require_POST
def add_to_cart(request, slug): # type: ignore
    quantity = request.POST.get("quantity", 1)

    try:
        quantity = int(quantity)
        if quantity < 1:
            raise ValueError
    except (TypeError, ValueError):
        messages.error(request, "Please enter a valid quantity.") # type: ignore
        return redirect("core:product_detail", slug=slug)

    with transaction.atomic():
        product = get_object_or_404(
            Product.objects.select_for_update(),
            slug=slug,
            is_available=True,
        )

        cart, _ = Cart.objects.get_or_create(customer=request.user)

        cart_item = CartItem.objects.filter(
            cart=cart,
            product=product,
        ).first()

        current_quantity = cart_item.quantity if cart_item else 0
        new_quantity = current_quantity + quantity

        if new_quantity > product.stock:
            messages.error(
                request,
                f"Only {product.stock} units of {product.name} are available."
            )
            return redirect("core:product_detail", slug=slug)

        if cart_item:
            CartItem.objects.filter(pk=cart_item.pk).update(
                quantity=F("quantity") + quantity
            )
        else:
            CartItem.objects.create(
                cart=cart,
                product=product,
                quantity=quantity,
            )

    messages.success(request, f"{product.name} added to your cart.")
    return redirect("core:cart")


@login_required
@require_POST
def update_cart(request, item_id):
    quantity = request.POST.get("quantity")

    try:
        quantity = int(quantity)
        if quantity < 0:
            raise ValueError
    except (TypeError, ValueError):
        messages.error(request, "Please enter a valid quantity.")
        return redirect("core:cart")

    cart = get_object_or_404(Cart, customer=request.user)

    with transaction.atomic():
        item = get_object_or_404(
            CartItem.objects.select_related("product"),
            pk=item_id,
            cart=cart,
        )

        if quantity == 0:
            item.delete()
            messages.success(request, "Item removed from your cart.")

        elif not item.product.is_available:
            messages.error(request, "This product is no longer available.")

        elif quantity > item.product.stock:
            messages.error(
                request,
                f"Only {item.product.stock} units of "
                f"{item.product.name} are available."
            )

        else:
            item.quantity = quantity
            item.save(update_fields=["quantity"])
            messages.success(request, "Cart updated successfully.")

    return redirect("core:cart")


@login_required
@require_POST
def delete_cart_item(request, item_id):
    cart = get_object_or_404(Cart, customer=request.user)

    item = get_object_or_404(
        CartItem,
        pk=item_id,
        cart=cart,
    )

    item.delete()

    messages.success(request, "Item removed from your cart.")

    return redirect("core:cart")

@login_required
@require_POST
def clear_cart(request):
    cart = get_object_or_404(Cart, customer=request.user)

    cart.items.all().delete() # type: ignore

    messages.success(request, "Your cart has been cleared.")

    return redirect("core:cart")

def wishlist(request):
    return render(request, 'core/wishlist.html')

def checkout(request):
    return render(request, 'core/checkout.html')

def order_detail(request, order_id):
    return render(request, 'core/order.html', {'order_id': order_id})


# ==========================================
# 1. ADVERTISEMENT VIEWS
# ==========================================

def advertisement_list(request):

  ads = Advertisement.objects.filter(status=Advertisement.Status.ACTIVE).order_by('-created_at')
  context = {'ads': ads}
  return render(request, 'marketing/ad_list.html', context)


def advertisement_detail(request, slug):
  ad = get_object_or_404(Advertisement, slug=slug)
  
  # Increment impressions view counter
  ad.impressions_count += 1
  ad.save(update_fields=['impressions_count'])

  context = {'ad': ad}
  return render(request, 'marketing/ad_detail.html', context)


@login_required
def advertisement_create(request):
  # Get stores owned by the user so they can optionally link the ad to their store
  user_stores = Store.objects.filter(vendor__user=request.user)

  if request.method == 'POST':
    title = request.POST.get('title')
    description = request.POST.get('description')
    target_url = request.POST.get('target_url')
    start_date = request.POST.get('start_date')
    end_date = request.POST.get('end_date')
    budget = request.POST.get('budget', 0.00)
    store_id = request.POST.get('store_id')  # Optional store selection
    banner_image = request.FILES.get('banner_image')

    store = user_stores.filter(id=store_id).first() if store_id else None

    Advertisement.objects.create(
        user=request.user,
        store=store,
        title=title,
        description=description,
        target_url=target_url,
        start_date=start_date,
        end_date=end_date,
        budget=budget,
        banner_image=banner_image,
        status=Advertisement.Status.PENDING # Default to pending approval
    )
    return redirect('advertisement-list')

  context = {'user_stores': user_stores}
  return render(request, 'marketing/ad_form.html', context)


@login_required
def advertisement_update(request, slug):
  ad = get_object_or_404(Advertisement, slug=slug, user=request.user)
  user_stores = Store.objects.filter(vendor__user=request.user)

  if request.method == 'POST':
    ad.title = request.POST.get('title', ad.title)
    ad.description = request.POST.get('description', ad.description)
    ad.target_url = request.POST.get('target_url', ad.target_url)
    
    store_id = request.POST.get('store_id')
    ad.store = user_stores.filter(id=store_id).first() if store_id else None

    if 'banner_image' in request.FILES:
      ad.banner_image = request.FILES['banner_image']

    ad.save()
    return redirect('advertisement-detail', slug=ad.slug)

  context = {'ad': ad, 'user_stores': user_stores}
  return render(request, 'marketing/ad_form.html', context)


@login_required
def advertisement_delete(request, slug):
  ad = get_object_or_404(Advertisement, slug=slug, user=request.user)
  if request.method == 'POST':
    ad.delete()
    return redirect('advertisement-list')

  context = {'ad': ad}
  return render(request, 'marketing/ad_confirm_delete.html', context)


# ==========================================
# 2. ANNOUNCEMENT VIEWS
# ==========================================

def announcement_list(request):
  
  announcements = Announcement.objects.filter(is_active=True).order_by('-created_at')
  context = {'announcements': announcements}
  return render(request, 'marketing/announcement_list.html', context)


def announcement_detail(request, slug):
  
  announcement = get_object_or_404(Announcement, slug=slug, is_active=True)
  context = {'announcement': announcement}
  return render(request, 'marketing/announcement_detail.html', context)


@login_required
def announcement_create(request):
  
  user_stores = Store.objects.filter(vendor__user=request.user)

  if request.method == 'POST':
    title = request.POST.get('title')
    content = request.POST.get('content')
    start_date = request.POST.get('start_date') or None
    end_date = request.POST.get('end_date') or None
    store_id = request.POST.get('store_id')
    banner_image = request.FILES.get('banner_image')

    store = user_stores.filter(id=store_id).first() if store_id else None

    Announcement.objects.create(
        user=request.user,
        store=store,
        title=title,
        content=content,
        start_date=start_date,
        end_date=end_date,
        banner_image=banner_image,
        is_active=True
    )
    return redirect('announcement-list')

  context = {'user_stores': user_stores}
  return render(request, 'marketing/announcement_form.html', context)


@login_required
def announcement_update(request, slug):
  
  announcement = get_object_or_404(Announcement, slug=slug, user=request.user)
  user_stores = Store.objects.filter(vendor__user=request.user)

  if request.method == 'POST':
    announcement.title = request.POST.get('title', announcement.title)
    announcement.content = request.POST.get('content', announcement.content)
    
    store_id = request.POST.get('store_id')
    announcement.store = user_stores.filter(id=store_id).first() if store_id else None

    if 'banner_image' in request.FILES:
      announcement.banner_image = request.FILES['banner_image']

    announcement.save()
    return redirect('announcement-detail', slug=announcement.slug)

  context = {'announcement': announcement, 'user_stores': user_stores}
  return render(request, 'marketing/announcement_form.html', context)


@login_required
def announcement_delete(request, slug):
  
  announcement = get_object_or_404(Announcement, slug=slug, user=request.user)
  if request.method == 'POST':
    announcement.delete()
    return redirect('announcement-list')

  context = {'announcement': announcement}
  return render(request, 'marketing/announcement_confirm_delete.html', context)

logger = logging.getLogger(__name__)


# ==========================================
# 1. CUSTOMER VIEWS (Placing & Viewing History)
# ==========================================
@login_required
def cart_detail(request):
    cart, _ = Cart.objects.get_or_create(customer=request.user)
    items = list(
        cart.items.select_related("product", "product__store").all() # type: ignore
    )

    # Group items by store so the customer sees how their cart splits per vendor
    grouped_by_store = defaultdict(lambda: {"items": [], "subtotal": Decimal("0.00")})
    for item in items:
        store = item.product.store
        grouped_by_store[store]["items"].append(item)
        grouped_by_store[store]["subtotal"] += item.line_total

    context = {
        "cart": cart,
        "items": items,
        "grouped_stores": dict(grouped_by_store),
    }
    return render(request, "transactions/cart_detail.html", context)


@login_required
def checkout(request):
    cart = get_object_or_404(Cart, customer=request.user)
    cart_items = list(
        cart.items.select_related("product", "product__store", "product__store__owner") # type: ignore
    )
    store = CartItem.objects.filter(cart=cart).first().product.store if cart_items else None # type: ignore
    
    if not cart_items:
        messages.warning(request, "Your cart is empty.")
        return redirect("transactions:cart_detail")

    # Pre-fill contact & campus residence details from CustomerProfile if available
    profile = getattr(request.user, "customer_profile", None)
    default_phone = getattr(profile, "phone", "") or getattr(request.user, "phone", "")
    residence = User.objects.filter(id=request.user.id).first().residence if hasattr(request.user, "residence") else "" # type: ignore
    room_number = User.objects.filter(id=request.user.id).first().room_number if hasattr(request.user, "room_number") else "" # type: ignore

    delivery_location = f"{residence} {room_number}".strip()
    pickup_location = Store.objects.filter(name=store.name).first().pickup_location if store else "" # type: ignore
    

    # Group items by store for display and per-store order creation
    items_by_store = defaultdict(list)
    for item in cart_items:
        items_by_store[item.product.store].append(item)

    if request.method == "POST":
        customer_name = (
            request.POST.get("customer_name", "").strip()
            or request.user.get_full_name()
            or request.user.email
        )
        customer_phone = request.POST.get("customer_phone", "").strip()
        fulfilment_method = request.POST.get(
            "fulfilment_method", Order.Fulfilment.PICKUP
        )
        pickup_location = request.POST.get("pickup_location", "").strip()
        delivery_address = request.POST.get("delivery_address", "").strip()
        payment_method = request.POST.get(
            "payment_method", Order.PaymentMethod.CASH
        )
        customer_note = request.POST.get("customer_note", "").strip()

        # Validate choice values against your TextChoices
        if fulfilment_method not in Order.Fulfilment.values:
            fulfilment_method = Order.Fulfilment.PICKUP
        if payment_method not in Order.PaymentMethod.values:
            payment_method = Order.PaymentMethod.CASH

        if not customer_phone:
            messages.error(request, "Please provide a phone or WhatsApp number so the store can contact you.")
            return redirect("transactions:checkout")

        if fulfilment_method == Order.Fulfilment.DELIVERY and not delivery_address:
            messages.error(request, "Please enter a delivery address or campus hall/room.")
            return redirect("transactions:checkout")

        shared_checkout_ref = uuid.uuid4()
        created_orders = []

        try:
            with transaction.atomic():
                # Lock all involved products to prevent overselling
                product_ids = [item.product_id for item in cart_items]
                locked_products = {
                    p.pk: p
                    for p in Product.objects.select_for_update().filter(pk__in=product_ids)
                }

                # Verify stock before creating any orders
                for item in cart_items:
                    product = locked_products[item.product_id]
                    if hasattr(product, "stock") and product.stock is not None:
                        if product.stock < item.quantity:
                            raise ValidationError(
                                f"Sorry, only {product.stock} unit(s) of '{product.name}' remain in stock."
                            )

                # Create one Order per store sharing the same checkout_reference
                for store, store_items in items_by_store.items():
                    order = Order.objects.create(
                        checkout_reference=shared_checkout_ref,
                        customer=request.user,
                        store=store,
                        customer_name=customer_name,
                        customer_phone=customer_phone,
                        customer_email=request.user.email,
                        fulfilment_method=fulfilment_method,
                        pickup_location=pickup_location,
                        delivery_address=delivery_address,
                        payment_method=payment_method,
                        customer_note=customer_note,
                    )

                    OrderItem.objects.bulk_create([
                        OrderItem(
                            order=order,
                            product=item.product,
                            product_name=item.product.name,
                            variant_name=item.variant_name,
                            sku=getattr(item.product, "sku", ""),
                            unit_price=item.product.price,
                            quantity=item.quantity,
                        )
                        for item in store_items
                    ])

                    # Deduct stock so RELEASES_STOCK on cancel/reject stays balanced
                    for item in store_items:
                        if hasattr(locked_products[item.product_id], "stock"):
                            Product.objects.filter(pk=item.product_id).update(
                                stock=F("stock") - item.quantity
                            )

                    # Calculate and freeze subtotal & total using your model method
                    order.recalculate_totals()
                    order.save(update_fields=["subtotal", "total"])

                    # Log initial status in OrderStatusHistory
                    OrderStatusHistory.objects.create(
                        order=order,
                        from_status="",
                        to_status=Order.Status.PENDING,
                        changed_by=request.user,
                        note="Order placed by customer.",
                    )

                    # Create portal message for the store's dashboard
                    items_lines = "\n".join(
                        f"- {i.quantity} × {i.product.name}"
                        f"{f' ({i.variant_name})' if i.variant_name else ''}"
                        f" — MUR {i.line_total}"
                        for i in store_items
                    )
                    location_info = (
                        f"Delivery to: {delivery_address}"
                        if fulfilment_method == Order.Fulfilment.DELIVERY
                        else f"Pickup at: {pickup_location or 'Campus / Store default'}"
                    )
                    portal_message = (
                        f"New Order {order.order_number} from {customer_name}\n"
                        f"Phone/WhatsApp: {customer_phone}\n"
                        f"Email: {request.user.email}\n"
                        f"Fulfilment: {order.get_fulfilment_method_display()} ({location_info})\n"
                        f"Payment: {order.get_payment_method_display()}\n"
                        f"Customer Note: {customer_note or 'None'}\n\n"
                        f"Items:\n{items_lines}\n\n"
                        f"Order Total: MUR {order.total}\n"
                        f"Please contact the customer to confirm and coordinate."
                    )

                    VendorNotification.objects.create(
                        store=store,
                        order=order,
                        title=f"New Order {order.order_number} (MUR {order.total})",
                        message=portal_message,
                    )

                    created_orders.append((store, order, portal_message))

                # Clear the cart once all orders succeed
                cart.items.all().delete() # type: ignore

        except ValidationError as exc:
            messages.error(request, exc.message)
            return redirect("transactions:cart_detail")

        # Send emails AFTER transaction commits so SMTP issues never roll back orders
        _send_order_notifications(request.user, customer_name, created_orders)

        return render(
            request,
            "transactions/checkout_success.html",
            {
                "orders": [order for _, order, _ in created_orders],
                "checkout_reference": shared_checkout_ref,
            },
        )

    context = {
        "cart": cart,
        "items": cart_items,
        "items_by_store": dict(items_by_store),
        "default_name": request.user.get_full_name() or "",
        "default_phone": default_phone,
        "delivery_location": delivery_location,
        "pickup_location": pickup_location,
        "fulfilment_choices": Order.Fulfilment.choices,
        "payment_choices": Order.PaymentMethod.choices,
    }
    return render(request, "transactions/checkout.html", context)


def _abs_url(base_url: str, path: str) -> str:
    if not path:
        return ""
    if path.startswith(("http://", "https://")):
        return path
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _build_order_email_payload(store, order, base_url: str, support_email: str) -> dict:
    """Prepares absolute image URLs, action links, and item data for HTML email templates."""
    store_logo_url = ""
    if getattr(store, "logo", None):
        store_logo_url = _abs_url(base_url, store.logo.url)

    store_url = _abs_url(
        base_url, reverse("store:store-profile", kwargs={"slug": store.slug})
    )
    review_url = _abs_url(
        base_url, reverse("store:submit-review", kwargs={"slug": store.slug})
    )
    # Adjust 'accounts:profile' to your dedicated order-tracking URL if you add one later
    track_url = f"{_abs_url(base_url, reverse('accounts:profile'))}?ref={order.checkout_reference}"

    vendor_email = getattr(store, "email", None) or getattr(store.owner, "email", "")
    vendor_phone = getattr(store, "contact_phone", "")
    contact_subject = quote(f"Question about Order {order.order_number} on The Spotlight")
    contact_store_url = (
        f"mailto:{vendor_email}?subject={contact_subject}"
        if vendor_email
        else store_url
    )

    report_subject = quote(
        f"[Issue Report] Order {order.order_number} (Ref: {order.checkout_reference})"
    )
    report_url = f"mailto:{support_email}?subject={report_subject}"

    items_data = []
    for item in order.items.select_related("product").all():
        image_url = ""
        if item.product and getattr(item.product, "image", None):
            image_url = _abs_url(base_url, item.product.image.url)
        items_data.append(
            {
                "name": item.display_name,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "line_total": item.line_total,
                "image_url": image_url,
            }
        )

    return {
        "store": store,
        "order": order,
        "store_logo_url": store_logo_url,
        "vendor_email": vendor_email,
        "vendor_phone": vendor_phone,
        "store_location": getattr(store, "location", "") or getattr(store, "address", ""),
        "store_url": store_url,
        "review_url": review_url,
        "track_url": track_url,
        "contact_store_url": contact_store_url,
        "report_url": report_url,
        "items": items_data,
    }


def _send_order_notifications(customer, customer_name, created_orders, request=None):
    sender = getattr(
        settings, "DEFAULT_FROM_EMAIL", "The Spotlight <e.mugisha7@gmail.com>"
    )
    support_email = getattr(settings, "SUPPORT_EMAIL", "e.mugisha7@gmail.com")
    base_url = (
        request.build_absolute_uri("/").rstrip("/")
        if request is not None
        else getattr(settings, "SITE_URL", "http://127.0.0.1:8000").rstrip("/")
    )

    enriched_orders = [
        _build_order_email_payload(store, order, base_url, support_email)
        for store, order, _ in created_orders
    ]

    # 1. Notify each seller/store via HTML + Plain Text email (includes full buyer details)
    for payload in enriched_orders:
        vendor_email = payload["vendor_email"]
        order = payload["order"]
        store = payload["store"]

        if vendor_email:
            html_body = render_to_string(
                "emails/vendor_new_order.html",
                {
                    **payload,
                    "buyer_name": customer_name,
                    "buyer_email": order.customer_email or customer.email,
                    "buyer_phone": order.customer_phone,
                    "support_email": support_email,
                },
            )
            text_body = strip_tags(html_body)

            msg = EmailMultiAlternatives(
                subject=f"[The Spotlight] New Order {order.order_number} — {store.name}",
                body=text_body,
                from_email=sender,
                to=[vendor_email],
                reply_to=[order.customer_email] if order.customer_email else None,
            )
            msg.attach_alternative(html_body, "text/html")
            msg.send(fail_silently=True)

    # 2. Send rich confirmation email to the customer
    if customer.email and enriched_orders:
        first_order = enriched_orders[0]["order"]
        checkout_ref = first_order.checkout_reference
        grand_total = sum(p["order"].total for p in enriched_orders)
        global_track_url = (
            f"{_abs_url(base_url, reverse('accounts:profile'))}?ref={checkout_ref}"
        )
        global_report_url = (
            f"mailto:{support_email}?subject="
            f"{quote(f'[Support Request] Checkout Ref {checkout_ref}')}"
        )

        html_body = render_to_string(
            "emails/customer_order_confirmation.html",
            {
                "customer_name": customer_name,
                "customer_email": customer.email,
                "checkout_reference": checkout_ref,
                "grand_total": grand_total,
                "orders_data": enriched_orders,
                "global_track_url": global_track_url,
                "global_report_url": global_report_url,
                "support_email": support_email,
            },
        )
        text_body = strip_tags(html_body)

        msg = EmailMultiAlternatives(
            subject=f"[The Spotlight] Order Confirmation — Ref #{str(checkout_ref)[:8].upper()}",
            body=text_body,
            from_email=sender,
            to=[customer.email],
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=True)

@login_required
def add_to_cart(request, product_id):
    product = get_object_or_404(Product, pk=product_id, is_available=True)

    # 1. If a logged-out user clicked "Add to Cart" and just finished logging in,
    # Django redirects them here via GET (?next=...). Send them back to the product page.
    if request.method != "POST":
        return redirect(request.META.get("HTTP_REFERER"))

    # 2. Prevent store owners from adding their own products
    if getattr(product.store, "owner_id", None) == request.user.id:
        msg = "You cannot add your own store's product to your cart."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"status": "error", "message": msg}, status=400)
        messages.warning(request, msg)
        return redirect(request.META.get("HTTP_REFERER", "marketplace:home"))

    # 3. Parse quantity, variant_name, and optional JSON customizations
    try:
        quantity = max(1, int(request.POST.get("quantity", 1)))
    except (ValueError, TypeError):
        quantity = 1

    variant_name = request.POST.get("variant_name", "").strip()

    raw_options = request.POST.get("selected_options", "")
    try:
        selected_options = json.loads(raw_options) if raw_options else {}
        if not isinstance(selected_options, dict):
            selected_options = {}
    except json.JSONDecodeError:
        selected_options = {}

    # 4. Add or increment inside an atomic transaction with stock checks
    with transaction.atomic():
        cart, _ = Cart.objects.get_or_create(customer=request.user)

        cart_item, created = CartItem.objects.select_for_update().get_or_create(
            cart=cart,
            product=product,
            variant_name=variant_name,
            defaults={
                "quantity": quantity,
                "selected_options": selected_options,
            },
        )

        new_quantity = quantity if created else cart_item.quantity + quantity

        # Enforce stock limit (if Product has a stock field)
        if hasattr(product, "stock") and product.stock is not None:
            if product.stock <= 0:
                if created:
                    cart_item.delete()
                msg = f"{product.name} is currently out of stock."
                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return JsonResponse({"status": "error", "message": msg}, status=400)
                messages.error(request, msg)
                return redirect(request.META.get("HTTP_REFERER", "marketplace:home"))

            if new_quantity > product.stock:
                new_quantity = product.stock
                messages.warning(
                    request,
                    f"Only {product.stock} unit(s) of {product.name} available; cart updated to max stock.",
                )

        if not created:
            cart_item.quantity = new_quantity
            if selected_options:
                cart_item.selected_options = selected_options
            cart_item.save(update_fields=["quantity", "selected_options"])
        elif new_quantity != quantity:
            cart_item.quantity = new_quantity
            cart_item.save(update_fields=["quantity"])

    success_msg = f"Added {quantity} × {product.name} to your cart."

    # 5. Support both AJAX (fetch) and standard form POST
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse(
            {
                "status": "ok",
                "message": success_msg,
                "cart_total_items": cart.total_items,
                "cart_subtotal": str(cart.subtotal),
            }
        )

    messages.success(request, success_msg)
    return redirect(request.META.get("HTTP_REFERER", "marketplace:home"))

@login_required
@require_POST
def update_cart_item(request, item_id):
    cart_item = get_object_or_404(CartItem, pk=item_id, cart__customer=request.user)
    try:
        quantity = int(request.POST.get("quantity", 1))
    except (ValueError, TypeError):
        quantity = 1

    if quantity <= 0:
        cart_item.delete()
        messages.info(request, "Item removed from your cart.")
    else:
        if hasattr(cart_item.product, "stock") and cart_item.product.stock is not None:
            quantity = min(quantity, cart_item.product.stock)
        cart_item.quantity = quantity
        cart_item.save(update_fields=["quantity"])
        messages.success(request, "Cart updated.")

    return redirect("transactions:cart_detail")


@login_required
@require_POST
def remove_cart_item(request, item_id):
    cart_item = get_object_or_404(CartItem, pk=item_id, cart__customer=request.user)
    cart_item.delete()
    messages.info(request, "Item removed from your cart.")
    return redirect("transactions:cart_detail")

@login_required
def customer_orders_list(request):
    my_orders = list(
        Order.objects.filter(customer=request.user)
        .select_related("store", "store__owner")
        .prefetch_related("items__product")
        .order_by("-created_at")
    )
    support_email = getattr(settings, "SUPPORT_EMAIL", "e.mugisha7@gmail.com")
    for order in my_orders:
        vendor_email = order.store.contact_email or order.store.owner.email
        edit_subject = quote(f"Edit request for order {order.order_number}")
        edit_body = quote(
            f"Hello {order.store.name},\n\n"
            f"I would like to request a change to order {order.order_number}."
        )
        report_subject = quote(f"[Issue Report] Order {order.order_number}")
        order.edit_request_url = (
            f"mailto:{vendor_email}?subject={edit_subject}&body={edit_body}"
            if vendor_email
            else ""
        )  # type: ignore[attr-defined]
        order.report_url = f"mailto:{support_email}?subject={report_subject}"  # type: ignore[attr-defined]

    return render(
        request,
        "transactions/customer_orders.html",
        {"orders": my_orders},
    )


@login_required
@require_POST
def cancel_customer_order(request, order_id):
    order = get_object_or_404(
        Order.objects.select_related("store"),
        pk=order_id,
        customer=request.user,
    )
    if not order.can_customer_cancel:
        messages.error(request, "Only pending orders can be cancelled.")
    else:
        try:
            order.change_status(
                Order.Status.CANCELLED,
                by=request.user,
                note="Cancelled by customer",
            )
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "Your order has been cancelled.")
    return redirect("transactions:customer-orders")


@login_required
@require_POST
def delete_customer_order(request, order_id):
    order = get_object_or_404(
        Order,
        pk=order_id,
        customer=request.user,
    )
    if order.status != Order.Status.CANCELLED:
        messages.error(request, "Only cancelled orders can be deleted.")
        return redirect("transactions:customer-orders")

    try:
        order.delete()
    except ProtectedError:
        messages.error(
            request,
            "This order cannot be deleted because it is linked to a review.",
        )
    else:
        messages.success(request, "The cancelled order has been deleted.")
    return redirect("transactions:customer-orders")


@login_required
def customer_bookings_list(request):
    tracking_reference = request.GET.get("ref", "").strip()
    bookings = Booking.objects.filter(customer=request.user)
    if tracking_reference:
        bookings = bookings.filter(reference=tracking_reference)

    my_bookings = list(
        bookings
        .select_related("service", "service__store", "service__store__owner", "slot")
        .order_by("-created_at")
    )
    support_email = getattr(settings, "SUPPORT_EMAIL", "e.mugisha7@gmail.com")
    for booking in my_bookings:
        vendor_email = booking.service.store.contact_email or booking.service.store.owner.email
        edit_subject = quote(f"Edit request for booking {booking.reference}")
        edit_body = quote(
            f"Hello {booking.service.store.name},\n\n"
            f"I would like to request a change to booking {booking.reference} "
            f"for {booking.service.name}."
        )
        report_subject = quote(f"[Issue Report] Booking {booking.reference}")
        booking.edit_request_url = ( # type: ignore
            f"mailto:{vendor_email}?subject={edit_subject}&body={edit_body}"
            if vendor_email
            else ""
        )
        booking.report_url = f"mailto:{support_email}?subject={report_subject}" # type: ignore

    return render(
        request,
        "transactions/customer_bookings.html",
        {"bookings": my_bookings, "tracking_reference": tracking_reference},
    )


@login_required
@require_POST
def cancel_customer_booking(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related("service", "slot"),
        pk=booking_id,
        customer=request.user,
    )
    try:
        booking.cancel_by_customer()
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "Your booking has been cancelled.")
    return redirect("transactions:customer-bookings")


@login_required
@require_POST
def delete_customer_booking(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id, customer=request.user)
    if booking.status not in (
        Booking.Status.CANCELLED_BY_CUSTOMER,
        Booking.Status.CANCELLED_BY_VENDOR,
    ):
        messages.error(request, "Only cancelled bookings can be deleted.")
        return redirect("transactions:customer-bookings")

    try:
        booking.delete()
    except ProtectedError:
        messages.error(
            request,
            "This booking cannot be deleted because it is linked to a review.",
        )
    else:
        messages.success(request, "The cancelled booking has been deleted.")
    return redirect("transactions:customer-bookings")



@login_required
def create_booking(request, store_slug, service_slug):
    store = Store.objects.filter(
        slug=store_slug,
        status=Store.Status.ACTIVE,
    ).first()
    if not store or not store.accepts_bookings:
        return redirect("stores-home")

    service = Service.objects.filter(
        slug=service_slug,
        store=store,
        is_available=True,
    ).first()
    if not service:
        return redirect("stores-home")

    slots = AvailabilitySlot.objects.all().filter(
        service=service,
        is_active=True,
    ).order_by("start_at")
    default_phone = getattr(request.user, "phone", "")
    form_data = {
        "customer_phone": default_phone,
        "seats": 1,
        "customer_note": "",
        "slot_id": "",
    }
    form_error = ""

    if request.method == "POST":
        form_data.update({
            "customer_phone": request.POST.get("customer_phone", "").strip(),
            "seats": request.POST.get("seats", "1").strip(),
            "customer_note": request.POST.get("customer_note", "").strip(),
            "slot_id": request.POST.get("slot_id", "").strip(),
        })

        try:
            seats = int(form_data["seats"])
        except (ValueError, TypeError):
            seats = 0

        if not form_data["customer_phone"]:
            form_error = "Enter a phone number so the provider can contact you."
        elif seats < 1:
            form_error = "Choose at least one seat."
        elif not form_data["slot_id"].isdigit():
            form_error = "Choose an available appointment time."
        else:
            slot = slots.filter(pk=form_data["slot_id"]).first()
            if not slot:
                form_error = "That time is no longer available. Please choose another."
            else:
                try:
                    with transaction.atomic():
                        booking = slot.book(
                            customer=request.user,
                            seats=seats,
                            note=form_data["customer_note"],
                            phone=form_data["customer_phone"],
                        )
                        VendorNotification.objects.create(
                            store=store,
                            title=f"New booking {booking.reference}",
                            message=(
                                f"New booking request from {request.user.get_full_name() or request.user.email}\n"
                                f"Service: {service.name}\n"
                                f"Date and time: {booking.start_at:%a, %d %b %Y, %H:%M}\n"
                                f"People: {booking.seats}\n"
                                f"Phone/WhatsApp: {booking.customer_phone}\n"
                                f"Customer email: {request.user.email}\n"
                                f"Customer note: {booking.customer_note or 'None'}\n"
                                f"Estimated total: MUR {booking.total_price}"
                            ),
                        )
                except ValidationError as error:
                    form_error = " ".join(error.messages)
                else:
                    _send_booking_notifications(request, booking)
                    messages.success(request, "Your booking request has been submitted.")
                    return render(
                        request,
                        "transactions/booking_success.html",
                        {"booking": booking},
                    )

    context = {
        "store": store,
        "service": service,
        "slots": slots,
        "default_name": request.user.get_full_name() or request.user.email,
        "default_email": request.user.email,
        "form_data": form_data,
        "form_error": form_error,
    }
    return render(request, "transactions/create_booking.html", context)


def _send_booking_notifications(request, booking):
    store = booking.service.store
    vendor_email = store.contact_email or store.owner.email
    sender = getattr(settings, "DEFAULT_FROM_EMAIL", "The Spotlight <noreply@example.com>")
    base_url = request.build_absolute_uri("/").rstrip("/")
    store_logo_url = _abs_url(base_url, store.logo.url) if store.logo else ""
    service_image_url = (
        _abs_url(base_url, booking.service.image.url) if booking.service.image else ""
    )
    common_context = {
        "booking": booking,
        "customer": booking.customer,
        "service": booking.service,
        "store": store,
        "store_logo_url": store_logo_url,
        "service_image_url": service_image_url,
        "store_url": _abs_url(
            base_url,
            reverse("store:store-profile", kwargs={"slug": store.slug}),
        ),
        "global_track_url": _abs_url(
            base_url,
            reverse("transactions:customer-bookings"),
        ) + f"?ref={booking.reference}",
    }

    email_jobs = [
        (
            booking.customer.email,
            f"[The Spotlight] Booking request received — {booking.reference}",
            "emails/customer_booking_confirmation.html",
            common_context,
        ),
        (
            vendor_email,
            f"[The Spotlight] New booking request — {booking.reference}",
            "emails/vendor_new_booking.html",
            common_context,
        ),
    ]

    for recipient, subject, template_name, context in email_jobs:
        if not recipient:
            continue
        html_body = render_to_string(template_name, context)
        message = EmailMultiAlternatives(
            subject=subject,
            body=strip_tags(html_body),
            from_email=sender,
            to=[recipient],
        )
        message.attach_alternative(html_body, "text/html")
        if not message.send(fail_silently=True):
            logger.warning(
                "Could not send booking notification email for booking %s.",
                booking.reference,
            )


# ==========================================
# 2. BUSINESS OWNER VIEWS (Fulfillment & Management)
# ==========================================

@login_required
def owner_orders_list(request):
  
  store = Store.objects.filter(vendor__user=request.user).first()
  if not store:
    return redirect('store-dashboard')

  orders = Order.objects.filter(store=store).order_by('-created_at')
  context = {'store': store, 'orders': orders}
  return render(request, 'transactions/owner_orders.html', context)


@login_required
def owner_bookings_list(request):
  
  store = Store.objects.filter(vendor__user=request.user).first()
  if not store:
    return redirect('store-dashboard')

  bookings = Booking.objects.filter(store=store).order_by('-booking_date')
  context = {'store': store, 'bookings': bookings}
  return render(request, 'transactions/owner_bookings.html', context)


@login_required
def update_order_status(request, order_id):
  
  order = Order.objects.filter(id=order_id, store__vendor__user=request.user).first()
  if not order:
    return redirect('store-dashboard')

  if request.method == 'POST':
    new_status = request.POST.get('status')
    if new_status:
      order.status = new_status
      order.save(update_fields=['status'])

  return redirect('owner-orders')


@login_required
def update_booking_status(request, booking_id):
  
  booking = Booking.objects.filter(id=booking_id, store__vendor__user=request.user).first()
  if not booking:
    return redirect('store-dashboard')

  if request.method == 'POST':
    new_status = request.POST.get('status')
    if new_status:
      booking.status = new_status
      booking.save(update_fields=['status'])

  return redirect('owner-bookings')