from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.network.health.domain.dtos import NodeHealthSearch
from src.modules.network.health.domain.models import NodeHealthModel
from src.modules.network.health.domain.results import NodeHealthFacts


class INodeHealthCommand(Protocol):
    def check(self, node_id: int) -> Awaitable[NodeHealthModel]: ...


class INodeHealthQuery(Protocol):
    def due_ids(self) -> Awaitable[list[int]]: ...
    def search(
        self, data: NodeHealthSearch
    ) -> Awaitable[ServicePage[NodeHealthFacts]]: ...
