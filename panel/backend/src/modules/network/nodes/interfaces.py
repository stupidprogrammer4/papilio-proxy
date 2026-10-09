from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.network.nodes.domain.dtos import (
    NodeCreate,
    NodeEnabled,
    NodeSearch,
    ProbeReceived,
)
from src.modules.network.nodes.domain.models import NodeModel, ProbeModel
from src.modules.network.nodes.domain.results import (
    NodeQuality,
    RegisteredNode,
)


class INodeService(Protocol):
    def authenticate(
        self, code: str, agent_key: str
    ) -> Awaitable[NodeModel]: ...
    def register(self, data: NodeCreate) -> Awaitable[RegisteredNode]: ...
    def set_enabled(
        self, id: int, data: NodeEnabled
    ) -> Awaitable[NodeModel]: ...
    def get(self, id: int) -> Awaitable[NodeModel]: ...
    def locked(self, id: int) -> Awaitable[NodeModel]: ...
    def search(
        self, data: NodeSearch
    ) -> Awaitable[ServicePage[NodeModel]]: ...


class IProbeCommand(Protocol):
    def receive(
        self, code: str, agent_key: str, data: ProbeReceived
    ) -> Awaitable[ProbeModel]: ...


class INodeQualityQuery(Protocol):
    def ranked(self, client_network: str) -> Awaitable[list[NodeQuality]]: ...
