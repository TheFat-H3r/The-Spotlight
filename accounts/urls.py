from django.urls import path
from django.contrib.auth.decorators import login_required
from .views import PasswordResetConfirmView, PasswordResetRequestView, ProfileView, RegisterView, LoginView, ResendVerificationEmailView, VerifyEmailConfirmView, logout_view, google_onboarding_view
from .utils import redirect_by_role


# Wrapper view to pass request.user into your redirect helper
@login_required
def home_redirect_view(request):
    return redirect_by_role(request.user)

app_name = "accounts"

urlpatterns = [
    path("", home_redirect_view, name="home"),
    path("register/", RegisterView.as_view(), name="register"),
    path('verify/<str:token>/', VerifyEmailConfirmView.as_view(), name='verify_email_confirm'),
    path('resend-verification/', ResendVerificationEmailView.as_view(), name='resend_verification'),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", logout_view, name="logout"),
    path("google/onboarding/", google_onboarding_view, name="google_onboarding"),
    path('profile/', ProfileView.as_view(), name='profile'),
    path('password-reset/', PasswordResetRequestView.as_view(), name='password_reset'),
    path('password-reset/confirm/<str:token>/', PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
]