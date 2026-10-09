from dishka import Provider, Scope, provide

from src.modules.network.nodes.app.commands import ProbeCommand
from src.modules.network.nodes.app.queries import NodeQualityQuery
from src.modules.network.nodes.app.services import NodeService
from src.modules.network.nodes.infra.mysql import (
    NodeRepository,
    ProbeRepository,
)
from src.modules.network.nodes.infra.readers import NodeQualityFactsReader
from src.modules.network.nodes.interfaces import (
    INodeQualityQuery,
    INodeService,
    IProbeCommand,
)


class NodeProvider(Provider):
    scope = Scope.REQUEST
    nodes = provide(NodeRepository)
    probes = provide(ProbeRepository)
    service = provide(NodeService, provides=INodeService)
    command = provide(ProbeCommand, provides=IProbeCommand)
    facts = provide(NodeQualityFactsReader)
    quality = provide(NodeQualityQuery, provides=INodeQualityQuery)
