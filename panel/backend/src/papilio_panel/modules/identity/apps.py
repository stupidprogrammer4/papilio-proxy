"""Native Django identity app discovery."""

from importlib import import_module

from django.apps import AppConfig


class IdentityConfig(AppConfig):
    name = "papilio_panel.modules.identity"
    label = "identity"

    def ready(self) -> None:
        import_module("papilio_panel.modules.identity.routers.openapi")
