from django.shortcuts import redirect
from .models import User, VendorApplication
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from django.conf import settings

def send_verification_email(user_email: str, user_name: str, verification_url: str) -> bool:
    """Sends account verification link using Brevo Transactional Email API."""
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = settings.BREVO_API_KEY

    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))

    sender = {
        "name": "The Spotlight",
        "email": "e.mugisha7@alustudent.com"
    }
    to = [{"email": user_email, "name": user_name}]

    html_content = f"""
    <!DOCTYPE html>
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #0f172a; color: #ffffff; padding: 20px;">
        <div style="max-width: 500px; margin: 0 auto; background-color: #1e293b; padding: 30px; border-radius: 16px; border: 1px solid #334155;">
          <h2 style="color: #ffffff; text-align: center;">Verify Your Account</h2>
          <p style="color: #94a3b8;">Hi {user_name},</p>
          <p style="color: #94a3b8;">Thank you for registering at <strong>The Spotlight</strong>. Please click the button below to confirm your email address and activate your account:</p>
          <div style="text-align: center; margin: 30px 0;">
            <a href="{verification_url}" style="background-color: #06b6d4; color: #0f172a; font-weight: bold; padding: 12px 24px; text-decoration: none; border-radius: 10px; display: inline-block;">Verify Email Address</a>
          </div>
          <p style="color: #64748b; font-size: 12px; text-align: center;">This link will expire in 24 hours. If you didn't create an account, you can safely ignore this message.</p>
        </div>
      </body>
    </html>
    """

    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=to,
        sender=sender,
        subject="Verify Your Spotlight Account Email",
        html_content=html_content
    )

    try:
        api_instance.send_transac_email(send_smtp_email)
        return True
    except ApiException as e:
        print(f"Brevo API Error: {e}")
        return False
    
def send_password_reset_email(user_email: str, user_name: str, reset_url: str) -> bool:
    """Sends password reset link using Brevo Transactional Email API."""
    api_key = getattr(settings, 'BREVO_API_KEY', '').strip()
    if not api_key:
        print("Brevo Error: BREVO_API_KEY is missing or empty.")
        return False

    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = api_key

    api_client = sib_api_v3_sdk.ApiClient(configuration)
    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(api_client)

    sender = {
        "name": "The Spotlight",
        "email": "e.mugisha7@alustudent.com"
    }
    to = [{"email": user_email, "name": user_name}]

    html_content = f"""
    <!DOCTYPE html>
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #0f172a; color: #ffffff; padding: 20px;">
        <div style="max-width: 500px; margin: 0 auto; background-color: #1e293b; padding: 30px; border-radius: 16px; border: 1px solid #334155;">
          <h2 style="color: #ffffff; text-align: center;">Reset Your Password</h2>
          <p style="color: #94a3b8;">Hi {user_name},</p>
          <p style="color: #94a3b8;">We received a request to reset the password for your <strong>The Spotlight</strong> account. Click the button below to choose a new password:</p>
          <div style="text-align: center; margin: 30px 0;">
            <a href="{reset_url}" style="background-color: #06b6d4; color: #0f172a; font-weight: bold; padding: 12px 24px; text-decoration: none; border-radius: 10px; display: inline-block;">Reset Password</a>
          </div>
          <p style="color: #64748b; font-size: 12px; text-align: center;">This link will expire in 15 minutes. If you didn't request a password reset, you can safely ignore this email.</p>
        </div>
      </body>
    </html>
    """

    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=to,
        sender=sender,
        subject="Reset Your Spotlight Account Password",
        html_content=html_content
    )

    try:
        api_instance.send_transac_email(send_smtp_email)
        return True
    except Exception as e:
        print(f"Error sending password reset email via Brevo: {e}")
        return False

    
def redirect_by_role(user):
    """Routes authenticated users based on role and onboarding completion."""
    if user.role == User.Role.ADMIN or user.is_superuser:
        return redirect('/admin/')

    if user.role == User.Role.VENDOR:
        has_profile = hasattr(user, 'vendor_profile')
        has_application = VendorApplication.objects.filter(applicant=user).exists()

        # Redirect to vendor application if not yet submitted
        if not has_profile and not has_application:
            return redirect('accounts:vendor_application')

        return redirect('marketplace:home')

    # Default: CUSTOMER
    return redirect('marketplace:home')