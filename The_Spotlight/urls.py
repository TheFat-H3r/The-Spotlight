from django.contrib import admin
from django.urls import include, path
from django.conf.urls.static import static
from The_Spotlight import settings # type: ignore

urlpatterns = [
    path('', include('core.urls')),
    path('admin/', admin.site.urls),
    path('portal/', include('operations.urls')),
    path('', include('accounts.urls')),
    path("auth/", include("allauth.urls")),
    path('stores/', include('stores.urls')),
    path('', include('transactions.urls')),
    path('', include('marketing.urls')),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)