"""Register native node metadata and schedule initialization."""

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class NodesConfig(AppConfig):
    name = "papilio_panel.modules.nodes"
    label = "nodes"

    def ready(self) -> None:
        from .infra.schedules import initialize_nodes

        post_migrate.connect(initialize_nodes, sender=self, dispatch_uid="papilio.nodes.initialize")
