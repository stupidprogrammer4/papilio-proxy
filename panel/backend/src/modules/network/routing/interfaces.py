from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.network.routing.domain.dtos import (
    GroupWrite,
    HostWrite,
    MembershipWrite,
    RoutingSearch,
)
from src.modules.network.routing.domain.models import (
    HostGroupModel,
    HostMembershipModel,
    HostModel,
)
from src.modules.network.routing.domain.results import GroupHostFacts


class IHostService(Protocol):
    def create(
        self, configuration_id: int, data: HostWrite
    ) -> Awaitable[HostModel]: ...
    def update(self, id: int, data: HostWrite) -> Awaitable[HostModel]: ...
    def get(self, id: int) -> Awaitable[HostModel]: ...
    def search(
        self, configuration_id: int | None, data: RoutingSearch
    ) -> Awaitable[ServicePage[HostModel]]: ...


class IHostGroupService(Protocol):
    def create(self, data: GroupWrite) -> Awaitable[HostGroupModel]: ...
    def update(
        self, id: int, data: GroupWrite
    ) -> Awaitable[HostGroupModel]: ...
    def get(self, id: int) -> Awaitable[HostGroupModel]: ...
    def search(
        self, data: RoutingSearch
    ) -> Awaitable[ServicePage[HostGroupModel]]: ...


class IHostMembershipService(Protocol):
    def get(
        self, group_id: int, host_id: int
    ) -> Awaitable[HostMembershipModel | None]: ...
    def put(
        self, group_id: int, host_id: int, data: MembershipWrite
    ) -> Awaitable[HostMembershipModel]: ...
    def remove(self, group_id: int, host_id: int) -> Awaitable[None]: ...


class IGroupHostQuery(Protocol):
    def search(
        self, group_id: int, data: RoutingSearch
    ) -> Awaitable[ServicePage[GroupHostFacts]]: ...
