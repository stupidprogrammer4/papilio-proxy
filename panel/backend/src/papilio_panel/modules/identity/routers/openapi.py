"""Register the native session schema for the challenge-aware subclass."""

from drf_spectacular.authentication import SessionScheme


class AdminSessionScheme(SessionScheme):
    target_class = (
        "papilio_panel.modules.identity.routers.session_authentication.AdminSessionAuthentication"
    )
