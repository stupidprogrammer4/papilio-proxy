"""Native shop model/task discovery and missing-only Beat initialization."""

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class ShopConfig(AppConfig):
    name = "papilio_panel.modules.shop"
    label = "shop"

    def ready(self) -> None:
        from .infra.schedules import initialize_shop

        post_migrate.connect(initialize_shop, sender=self, dispatch_uid="papilio.shop.initialize")
