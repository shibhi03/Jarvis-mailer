from django.urls import path
from accounts import views

urlpatterns = [
    path("google/login/", views.google_login, name="google-login"),
    path("google/callback/", views.google_callback, name="google-callback"),
    path("logout/", views.disconnect_gmail, name="disconnect-gmail"),
    path("status/", views.auth_status, name="auth-status"),
]
