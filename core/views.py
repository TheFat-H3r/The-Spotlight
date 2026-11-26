from django.shortcuts import get_object_or_404, redirect, render

from marketing.models import Advertisement, Announcement
from stores.models import Category, Product, Review, Service, Store

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
    return render(request, 'core/product_list.html')

def product_detail(request, slug):
    return render(request, 'core/product_detail.html', {'slug': slug})

def service_list(request):
    return render(request, 'core/service_list.html')

def service_detail(request, slug):
    return render(request, 'core/service_detail.html', {'slug': slug})

def category_detail(request, slug):
    return render(request, 'core/category_detail.html', {'category_slug': slug})

def store_list(request):
    stores = Store.objects.filter(status="active")
    
    context = {
        "stores": stores,
    }
    
    return render(request, 'core/store_list.html', context)

from django.shortcuts import get_object_or_404, render

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
def cart(request):
    return render(request, 'core/cart.html')

def wishlist(request):
    return render(request, 'core/wishlist.html')

def checkout(request):
    return render(request, 'core/checkout.html')

def order_detail(request, order_id):
    return render(request, 'core/order.html', {'order_id': order_id})