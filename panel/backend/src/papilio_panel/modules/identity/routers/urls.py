"""Identity HTTP resource paths."""

from django.urls import path

from .authentication import CsrfView, LoginView, LogoutView, SessionView
from .setup import OwnerSetupView

urlpatterns = [
    path("admin/auth/csrf", CsrfView.as_view()),
    path("admin/auth/login", LoginView.as_view()),
    path("admin/auth/logout", LogoutView.as_view()),
    path("admin/auth/me", SessionView.as_view()),
    path("setup/owner", OwnerSetupView.as_view()),
]
