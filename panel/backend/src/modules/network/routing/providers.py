from dishka import Provider, Scope, provide

from src.modules.network.routing.app.services import (
    GroupHostQuery,
    HostGroupService,
    HostMembershipService,
    HostService,
)
from src.modules.network.routing.infra.mysql import (
    HostGroupRepository,
    HostMembershipRepository,
    HostRepository,
)
from src.modules.network.routing.infra.readers import GroupHostReader
from src.modules.network.routing.interfaces import (
    IGroupHostQuery,
    IHostGroupService,
    IHostMembershipService,
    IHostService,
)


class RoutingProvider(Provider):
    scope = Scope.REQUEST
    hosts = provide(HostRepository)
    groups = provide(HostGroupRepository)
    members = provide(HostMembershipRepository)
    reader = provide(GroupHostReader)
    host_service = provide(HostService, provides=IHostService)
    group_service = provide(HostGroupService, provides=IHostGroupService)
    membership_service = provide(
        HostMembershipService, provides=IHostMembershipService
    )
    query = provide(GroupHostQuery, provides=IGroupHostQuery)
