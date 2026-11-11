from django.shortcuts import get_object_or_404, render
from .models import Store, Category, BusinessType


def marketplace_home(request):
    """Public marketplace home page displaying featured stores and categories."""
    featured_stores = Store.objects.public().filter(is_featured=True)[:6] # type: ignore
    all_stores = Store.objects.public()[:12] # type: ignore
    business_types = BusinessType.objects.filter(is_active=True)
    featured_categories = Category.objects.filter(is_active=True, is_featured=True)[:8]

    context = {
        "featured_stores": featured_stores,
        "all_stores": all_stores,
        "business_types": business_types,
        "featured_categories": featured_categories,
    }
    return render(request, "marketplace/home.html", context)


def store_detail(request, slug):
    """Detailed public profile view for an individual vendor store."""
    store = get_object_or_404(Store.objects.public(), slug=slug) # type: ignore
    context = {
        "store": store,
    }
    return render(request, "marketplace/store_detail.html", context)


def category_detail(request, slug):
    """List public stores filtered under a specific category."""
    category = get_object_or_404(Category, slug=slug, is_active=True)
    stores = Store.objects.public().filter(categories=category) # type: ignore
    context = {
        "category": category,
        "stores": stores,
    }
    return render(request, "marketplace/category_detail.html", context)


def business_type_detail(request, slug):
    """List public stores filtered under a specific business type (e.g. Food, Transport)."""
    business_type = get_object_or_404(BusinessType, slug=slug, is_active=True)
    stores = Store.objects.public().filter(business_type=business_type) # type: ignore
    context = {
        "business_type": business_type,
        "stores": stores,
    }
    return render(request, "marketplace/business_type_detail.html", context)