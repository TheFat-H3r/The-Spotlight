from .views import (
    RegisterView, 
    LoginView, 
    logout_view, 
    PasswordResetConfirmView, 
    PasswordResetRequestView, 
    ProfileView, 
    ResendVerificationEmailView, 
    VerifyEmailConfirmView,
    user_settings
)

from django.urls import path

app_name = 'accounts'

urlpatterns = [
    # path("", home_redirect_view, name="home"),
    path("register/", RegisterView.as_view(), name="register"),
    path('verify/<str:token>/', VerifyEmailConfirmView.as_view(), name='verify_email_confirm'),
    path('resend-verification/', ResendVerificationEmailView.as_view(), name='resend_verification'),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", logout_view, name="logout"),
    path('profile/', ProfileView.as_view(), name='profile'),
    path('password-reset/', PasswordResetRequestView.as_view(), name='password_reset'),
    path('password-reset/confirm/<str:token>/', PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('user-setting/', user_settings, name='user-settings')
    
]