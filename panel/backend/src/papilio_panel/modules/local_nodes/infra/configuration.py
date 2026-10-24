"""Read installation capabilities and initial defaults without changing persisted choices."""

from django.conf import settings

from papilio_panel.modules.nodes.domain import NodeDefinition

from ..domain import LocalDefaults, LocalDefinition


class NativeLocalConfiguration:
    def defaults(self) -> LocalDefaults:
        return LocalDefaults(
            settings.PAPILIO_LOCAL_NODE_AVAILABLE,
            LocalDefinition(
                NodeDefinition("Local node", settings.PAPILIO_LOCAL_NODE_ENDPOINT),
                "Local Xray",
                "vless",
                settings.PAPILIO_LOCAL_NODE_PUBLIC_HOST,
                settings.PAPILIO_LOCAL_NODE_PUBLIC_PORT,
                bind_address=settings.PAPILIO_LOCAL_NODE_BIND_ADDRESS,
                bind_port=settings.PAPILIO_LOCAL_NODE_BIND_PORT,
            ),
        )
