from django.shortcuts import redirect
from .models import User
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

    
def redirect_by_role(user):
    """Redirects the user to their respective dashboard route based on their role."""
    if user.is_platform_admin or user.is_superuser:
        return redirect("admin_dashboard")
    elif user.is_vendor:
        return redirect("vendor_dashboard")
    else:
        return redirect("customer_dashboard")