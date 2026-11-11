from django.urls import path
from django.contrib.auth.decorators import login_required
from .views import RegisterView, LoginView, logout_view, google_onboarding_view, password_reset_view
from .utils import redirect_by_role


# Wrapper view to pass request.user into your redirect helper
@login_required
def home_redirect_view(request):
    return redirect_by_role(request.user)

app_name = "accounts"

urlpatterns = [
    path("", home_redirect_view, name="home"),
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", logout_view, name="logout"),
    path("google/onboarding/", google_onboarding_view, name="google_onboarding"),
    path("password_reset/", password_reset_view, name="password_reset"),
]