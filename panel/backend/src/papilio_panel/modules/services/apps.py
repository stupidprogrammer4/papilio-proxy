"""Discover native service persistence and seed only its missing delivery schedule."""

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class ServicesConfig(AppConfig):
    name = "papilio_panel.modules.services"
    label = "services"

    def ready(self) -> None:
        from .infra.schedules import initialize_services

        post_migrate.connect(
            initialize_services, sender=self, dispatch_uid="papilio.services.initialize"
        )
