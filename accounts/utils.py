from django.shortcuts import redirect
from .models import User


def redirect_by_role(user):
    """Redirects the user to their respective dashboard route based on their role."""
    if user.is_platform_admin or user.is_superuser:
        return redirect("admin_dashboard")
    elif user.is_vendor:
        return redirect("vendor_dashboard")
    else:
        return redirect("customer_dashboard")