from dishka import Provider, Scope, provide

from src.config.settings import PapilioSettings
from src.modules.network.node_capabilities.app.commands import (
    NodeCapabilityCommand,
    capability_conflict,
)
from src.modules.network.node_capabilities.app.queries import (
    NodeCapabilityQuery,
)
from src.modules.network.node_capabilities.app.services import (
    NodeCapabilityService,
)
from src.modules.network.node_capabilities.domain.contracts import (
    NodeCapabilityCapacity,
)
from src.modules.network.node_capabilities.infra.mysql import (
    NodeCapabilityObservationRepository,
)
from src.modules.network.node_capabilities.infra.readers import (
    NodeCapabilityObservationReader,
)
from src.modules.network.node_capabilities.interfaces import (
    INodeCapabilityCommand,
    INodeCapabilityQuery,
    INodeCapabilityService,
)


class NodeCapabilityProvider(Provider):
    scope = Scope.REQUEST
    repo = provide(NodeCapabilityObservationRepository)
    reader = provide(NodeCapabilityObservationReader)
    service = provide(NodeCapabilityService, provides=INodeCapabilityService)
    command = provide(NodeCapabilityCommand, provides=INodeCapabilityCommand)
    query = provide(NodeCapabilityQuery, provides=INodeCapabilityQuery)

    @provide
    def capacity(self, settings: PapilioSettings) -> NodeCapabilityCapacity:
        if settings.node_capabilities is None:
            raise capability_conflict("capability_observations_unconfigured")
        return settings.node_capabilities
