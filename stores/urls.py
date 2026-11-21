from django.urls import path
from .views import all_products, all_services, product_info, store_create, store_dashboard, store_delete, store_toggle_orders, store_update, store, product_detail, service_detail, stores_list, submit_store_review

app_name = "store"
urlpatterns = [
    # Public routes
    path('', stores_list, name='stores-home'),
    path('all', stores_list, name='store-list'),
    path('services/all', all_services, name='store-services-list'),
    path('products/all', all_products, name='store-products-list'),
    path('<slug:slug>/', store, name='store-profile'),
    path("<slug:slug>/review/", submit_store_review, name="submit-review"),
    path('product/<slug:slug>/', product_detail, name='product-detail'),
    path('service/<slug:slug>/', service_detail, name='service-detail'),
    path('product/<slug:slug>/info/', product_info, name='product-info'),

    # Vendor management CRUD routes
    path('dashboard/', store_dashboard, name='store-dashboard'),
    path('create/store', store_create, name='store-create'),
    path('<slug:slug>/edit/', store_update, name='store-update'),
    path('<slug:slug>/delete/', store_delete, name='store-delete'),

    # Operational actions
    path('<slug:slug>/toggle-orders/', store_toggle_orders, name='store-toggle-orders'),
]