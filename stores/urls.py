from django.urls import path
from .views import store_create, store_dashboard, store_delete, store_toggle_orders, store_update, stores_home, store, product_detail, service_detail

app_name = "store"
urlpatterns = [
    # Public routes
    path('', stores_home, name='stores-home'),
    path('<slug:slug>/', store, name='store-profile'),
    path('product/<slug:slug>/', product_detail, name='product-detail'),
    path('service/<slug:slug>/', service_detail, name='service-detail'),

    # Vendor management CRUD routes
    path('dashboard/', store_dashboard, name='store-dashboard'),
    path('create/store', store_create, name='store-create'),
    path('<slug:slug>/edit/', store_update, name='store-update'),
    path('<slug:slug>/delete/', store_delete, name='store-delete'),

    # Operational actions
    path('<slug:slug>/toggle-orders/', store_toggle_orders, name='store-toggle-orders'),
]