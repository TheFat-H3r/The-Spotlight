# myproject/urls.py
from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from django.conf.urls.static import static
from The_Spotlight import settings

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("marketplace.urls", namespace="marketplace")),
    path("accounts/", include("accounts.urls", namespace="users")),
    path("accounts/", include("allauth.urls")),
    
    
    # Role-based dashboard routes
    path("dashboards/customer/", TemplateView.as_view(template_name="dashboards/customer.html"), name="customer_dashboard"),
    path("dashboards/vendor/", TemplateView.as_view(template_name="dashboards/vendor.html"), name="vendor_dashboard"),
    path("dashboards/admin/", TemplateView.as_view(template_name="dashboards/admin.html"), name="admin_dashboard"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)