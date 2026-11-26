from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from marketing.models import Advertisement, Announcement
from stores.models import Category, Product, Review, Service, Store
from transactions.models import Cart, CartItem

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

    related_products = Product.objects.none()

    if product.category_id:
        related_products = (
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
        "related_products": related_products,
    }
    print("related_products")

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
def cart_detail(request):
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
def add_to_cart(request, slug):
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