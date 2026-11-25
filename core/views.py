from django.shortcuts import render

# --- Main & Static Pages ---
def home(request):
    return render(request, 'core/home.html')

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
    return render(request, 'core/store_list.html')

def store_detail(request, slug):
    return render(request, 'core/store_detail.html', {'slug': slug})

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