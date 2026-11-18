from django.urls import path
from .views import store_create, store_dashboard, store_delete, store_toggle_orders, store_update, stores_home, store

app_name = "store"
urlpatterns = [
    # Public routes
    path('', stores_home, name='stores-home'),
    path('<slug:slug>/', store, name='store-profile'),

    # Vendor management CRUD routes
    path('dashboard/', store_dashboard, name='store-dashboard'),
    path('create/store', store_create, name='store-create'),
    path('<slug:slug>/edit/', store_update, name='store-update'),
    path('<slug:slug>/delete/', store_delete, name='store-delete'),

    # Operational actions
    path('<slug:slug>/toggle-orders/', store_toggle_orders, name='store-toggle-orders'),
]