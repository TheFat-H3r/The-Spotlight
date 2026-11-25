from django.urls import path
from .views import (
    home, 
    about_us, 
    contact_us, 
    contact_support,
    faq_help,
    privacy_policy,
    terms_of_service,
    community_guidelines,
)

app_name = "core"

urlpatterns = [
    path("", home, name="home"),
    path("contact_us/", contact_us, name="contact_us"),
    path("about_us/", about_us, name="about_us"),
    path("support/", contact_support, name='contact-support'),
    path("faq/", faq_help, name="faq"),
    path("privacy-policy/", privacy_policy, name="privacy-policy"),
    path("terms/", terms_of_service, name="terms"),
    path("community-guidelines/", community_guidelines, name="community-guidelines"),
    
]