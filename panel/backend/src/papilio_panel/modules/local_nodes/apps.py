"""Native local runtime model/task discovery and missing schedule initialization."""

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class LocalNodesConfig(AppConfig):
    name = "papilio_panel.modules.local_nodes"
    label = "local_nodes"

    def ready(self) -> None:
        from .infra.schedules import initialize_local_nodes

        post_migrate.connect(
            initialize_local_nodes, sender=self, dispatch_uid="papilio.local_nodes.initialize"
        )
