from django.db.models.signals import post_save
from django.dispatch import receiver
from allauth.socialaccount.signals import pre_social_login
from .models import User, CustomerProfile


@receiver(post_save, sender=User)
def create_or_update_customer_profile(sender, instance, created, **kwargs):
    """Automatically create a CustomerProfile when a new User registers."""
    if created:
        CustomerProfile.objects.create(user=instance)


@receiver(pre_social_login)
def populate_google_data(request, sociallogin, **kwargs):
    """Set provider flags and google_id when logging in with Google."""
    if sociallogin.account.provider == "google":
        user = sociallogin.user
        extra_data = sociallogin.account.extra_data
        
        # Populate custom identity fields
        user.auth_provider = User.AuthProvider.GOOGLE
        user.google_id = sociallogin.account.uid
        
        if not user.full_name:
            user.full_name = extra_data.get("name", "")
            
        user.is_email_verified = True