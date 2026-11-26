# core/urls.py
from django.urls import path
from .views import (
    home, about, contact, faq, privacy, report, terms,
    login_view, create_account, user_profile, become_vendor,
    product_list, product_detail, category_detail,
    service_list, service_detail, store_list, store_detail, flash_sale,
    cart, wishlist, checkout, order_detail,
)

app_name = 'core'

urlpatterns = [
    # Main & Static Pages
    path('', home, name='home'),
    path('about/', about, name='about'),
    path('contact/', contact, name='contact'),
    path('faq/', faq, name='faq'),
    path('report/<slug:slug>/<slug:store>', report, name='report'),
    path('privacy-policy/', privacy, name='privacy'),
    path('terms-of-service/', terms, name='terms'),

    # Authentication & User Account
    path('login/', login_view, name='login'),
    path('register/', create_account, name='create_account'),
    path('profile/', user_profile, name='user_profile'),
    path('become-vendor/', become_vendor, name='become_vendor'),

    # Catalog: Products, Services & Stores
    path('flash-sales/', product_list, name='flash_sale_list'),
    path('products/', product_list, name='product_list'),
    path('products/<slug:slug>/', product_detail, name='product_detail'),
    path('categories/', category_detail, name='category_list'),
    path('category/<slug:slug>/', category_detail, name='category_detail'),
    path('services/', service_list, name='service_list'),
    path('services/<slug:slug>/', service_detail, name='service_detail'),
    path('stores/', store_list, name='store_list'),
    path('stores/<slug:slug>/', store_detail, name='store_detail'),
    path('flash-sale/', flash_sale, name='flash_sale'),

    # Shopping & Orders
    path('cart/', cart, name='cart'),
    path('wishlist/', wishlist, name='wishlist'),
    path('checkout/', checkout, name='checkout'),
    path('orders/<int:order_id>/', order_detail, name='order_detail'),
]