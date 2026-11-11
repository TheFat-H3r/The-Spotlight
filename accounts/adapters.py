# users/adapters.py
from allauth.account.adapter import DefaultAccountAdapter
from django.urls import reverse
from .utils import redirect_by_role
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from typing import TYPE_CHECKING


class CustomAccountAdapter(DefaultAccountAdapter):
    def get_login_redirect_url(self, request):
        user = request.user
        if not user or not user.is_authenticated:
            return reverse("users:login")

        # redirect_by_role returns an HttpResponseRedirect; extract url string for allauth
        response = redirect_by_role(user)
        return response.url

if TYPE_CHECKING:
    from accounts.models import User  # Replace with your app name


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        # Type cast request.user or the returned user
        custom_user = user  # type: User
        custom_user.auth_provider = custom_user.AuthProvider.GOOGLE
        custom_user.google_id = sociallogin.account.uid
        custom_user.is_email_verified = True
        custom_user.role = custom_user.Role.CUSTOMER
        custom_user.save()
        return custom_user

    def get_login_redirect_url(self, request):
        user = request.user
        if not user.is_authenticated:
            return reverse("accounts:login")
        
        # If they registered via Google and haven't set up their profile/role info yet
        if user.auth_provider == user.AuthProvider.GOOGLE and not getattr(user, "_onboarding_complete", False):
            # Check if customer or vendor profile fields are empty/uninitialized
            if user.role == user.Role.CUSTOMER and not hasattr(user, "customer_profile"):
                return reverse("accounts:google_onboarding")
        
        from .utils import redirect_by_role
        return redirect_by_role(user).url