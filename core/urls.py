from django.urls import path
from .views import home, about_us, contact_us, contact_support

app_name = "core"

urlpatterns = [
    path("", home, name="home"),
    path("contact_us/", contact_us, name="contact_us"),
    path("about_us/", about_us, name="about_us"),
    path("support/", contact_support, name='contact-support'),
    
]