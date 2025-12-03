from django.urls import path

from . import views

app_name = "accounts_plus"

urlpatterns = [
    path("accounts/login/", views.login_user, name="login"),
    path("accounts/register/", views.register_user, name="register"),
    path("accounts/register/user/", views.register_user, name="register_user"),
]
