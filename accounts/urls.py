from django.urls import path
from django.shortcuts import redirect

from .views import (
    RegisterView,
    LoginView,
    logout_view,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    ProfileView,
    ResendVerificationEmailView,
    VerifyEmailConfirmView,
    user_settings,
    settings_profile_view,
    settings_notifications_view,
    settings_preferences_view,
    settings_privacy_view,
    settings_password_change_view,
    settings_sessions_view,
    delete_account_view,
)

app_name = 'accounts'

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("verify/<str:token>/", VerifyEmailConfirmView.as_view(), name="verify_email_confirm"),
    path("resend-verification/", ResendVerificationEmailView.as_view(), name="resend_verification"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", logout_view, name="logout"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("password-reset/", PasswordResetRequestView.as_view(), name="password_reset"),
    path("password-reset/confirm/<str:token>/", PasswordResetConfirmView.as_view(), name="password_reset_confirm"),

    # Settings routes
    path("user-settings/", lambda request: redirect("accounts:settings", permanent=False), name="user-settings"),
    path("settings/", user_settings, name="settings"),
    path("settings/profile/", settings_profile_view, name="settings_profile"),
    path("settings/notifications/", settings_notifications_view, name="settings_notifications"),
    path("settings/preferences/", settings_preferences_view, name="settings_preferences"),
    path("settings/privacy/", settings_privacy_view, name="settings_privacy"),
    path("settings/password/", settings_password_change_view, name="password_change"),
    path("settings/sessions/", settings_sessions_view, name="sessions"),
    path("settings/delete/", delete_account_view, name="delete_account"),
]