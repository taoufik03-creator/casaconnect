from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "accounts"
urlpatterns = [
    path("login/", views.PBRLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("signup/", views.signup, name="signup"),
    path("forgot/", views.forgot_password, name="forgot_password"),
    path("forgot/reset/", views.reset_password, name="reset_password"),
    path("profile/", views.profile, name="profile"),
]
