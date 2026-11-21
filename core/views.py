from django.shortcuts import render
from decimal import Decimal, InvalidOperation
from django.db.models import Q

from marketing.models import Advertisement, Announcement, Announcement
from stores.models import BusinessType, Category, Product, Review, Service, Store

def home(request):
    query = request.GET.get("q", "").strip()
    vendor_type_slug = request.GET.get("vendor_type", "").strip()
    category_slug = request.GET.get("category", "").strip()
    max_price_raw = request.GET.get("max_price", "").strip()
    location = request.GET.get("location", "").strip()

    # Parse max_price safely
    max_price = None
    if max_price_raw:
        try:
            max_price = Decimal(max_price_raw)
        except InvalidOperation:
            max_price = None

    # 2. Base Querysets (only active/published records)
    active_ads = Advertisement.objects.filter(is_active=True).order_by("-created_at")

    featured_stores = (
        Store.objects.filter(status="active", is_featured=True)
        .select_related("business_type")
        .order_by("-rating_average", "name")
    )

    products = (
        Product.objects.filter(is_available=True)
        .select_related("store", "store__business_type", "category")
        .order_by("-is_featured", "-created_at")
    )

    services = (
        Service.objects.filter(is_available=True)
        .select_related("store", "store__business_type", "category")
        .order_by("-is_featured", "-created_at")
    )

    # 3. Apply Search & Sidebar Filters to Products, Services, and Stores
    if query:
        products = products.filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(store__name__icontains=query)
            | Q(category__name__icontains=query)
        )
        services = services.filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(store__name__icontains=query)
            | Q(category__name__icontains=query)
        )
        featured_stores = featured_stores.filter(
            Q(name__icontains=query)
            | Q(tagline__icontains=query)
            | Q(description__icontains=query)
        )

    if vendor_type_slug:
        products = products.filter(store__business_type__slug=vendor_type_slug)
        services = services.filter(store__business_type__slug=vendor_type_slug)
        featured_stores = featured_stores.filter(business_type__slug=vendor_type_slug)

    if category_slug:
        products = products.filter(category__slug=category_slug)
        services = services.filter(category__slug=category_slug)

    if max_price is not None and max_price >= 0:
        products = products.filter(price__lte=max_price)
        services = services.filter(starting_price__lte=max_price)

    if location:
        products = products.filter(store__location__icontains=location)
        services = services.filter(store__location__icontains=location)
        featured_stores = featured_stores.filter(location__icontains=location)

    # 4. Sidebar & Social Proof Sections
    business_types = BusinessType.objects.all().order_by("name")
    featured_categories = Category.objects.all().order_by("name")

    advertisements = (
        Advertisement.objects.filter(is_active=True)
        .select_related("store")
        .order_by("-created_at")[:4]
    )

    announcements = (
        Announcement.objects.filter(is_active=True)
        .order_by("-created_at")[:4]
    )

    featured_reviews = (
        Review.objects.filter(status="published")
        .select_related("author", "store")
        .order_by("-overall_rating", "-created_at")[:6]
    )
    context = {
        # "active_ads": active_ads, #Don't disclose by now
        "featured_stores": featured_stores[:12],
        "business_types": business_types,
        "featured_categories": featured_categories,
        "featured_products": products[:6],
        "featured_services": services[:4],
        "advertisements": advertisements,
        "announcements": announcements,
        "featured_reviews": featured_reviews,
    }

    return render(request, "core/home.html", context)

def about_us(request):
    return render(request, 'core/about.html')

def contact_us(request):
    return render(request, 'core/contact.html')