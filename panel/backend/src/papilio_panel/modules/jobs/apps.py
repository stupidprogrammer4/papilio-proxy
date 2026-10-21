"""Register only native post-migration schedule initialization."""

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class JobsConfig(AppConfig):
    name = "papilio_panel.modules.jobs"
    label = "jobs"

    def ready(self) -> None:
        from .infra.schedules import initialize_schedules

        post_migrate.connect(
            initialize_schedules, sender=self, dispatch_uid="papilio.jobs.initialize_schedules"
        )
