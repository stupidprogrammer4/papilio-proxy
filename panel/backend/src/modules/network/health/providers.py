from dishka import Provider, Scope, provide

from src.modules.network.health.app.commands import NodeHealthCommand
from src.modules.network.health.app.queries import NodeHealthQuery
from src.modules.network.health.infra.mysql import NodeHealthRepository
from src.modules.network.health.infra.readers import NodeHealthReader
from src.modules.network.health.interfaces import (
    INodeHealthCommand,
    INodeHealthQuery,
)
from src.modules.network.health.tasks.schedulers.checks import (
    CheckNodeHealth,
    ScanNodeHealth,
)


class NodeHealthProvider(Provider):
    scope = Scope.REQUEST
    repository = provide(NodeHealthRepository)
    reader = provide(NodeHealthReader)
    command = provide(NodeHealthCommand, provides=INodeHealthCommand)
    query = provide(NodeHealthQuery, provides=INodeHealthQuery)
    check_task = provide(CheckNodeHealth)
    scan_task = provide(ScanNodeHealth)
