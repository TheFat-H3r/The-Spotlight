from django.urls import path
from .views import (
    marketplace_home,
    store_detail,
    category_detail,
    business_type_detail,
)

app_name = "marketplace"

urlpatterns = [
    path("", marketplace_home, name="home"),
    path("store/<slug:slug>/", store_detail, name="store_detail"),
    path("category/<slug:slug>/", category_detail, name="category_detail"),
    path("type/<slug:slug>/", business_type_detail, name="business_type_detail"),
]