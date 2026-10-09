from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.network.node_capabilities.domain.contracts import (
    NodeCapabilityReceived,
    NodeCapabilitySearch,
)
from src.modules.network.node_capabilities.domain.models import (
    NodeCapabilityObservationModel,
)
from src.modules.network.node_capabilities.domain.results import (
    NodeCapabilityLatest,
    NodeCapabilityObservation,
    NodeCapabilityReceipt,
)


class INodeCapabilityService(Protocol):
    def find(
        self, node_id: int, report_id: str
    ) -> Awaitable[NodeCapabilityObservationModel | None]: ...
    def create(
        self, data: NodeCapabilityObservationModel
    ) -> Awaitable[NodeCapabilityObservationModel]: ...


class INodeCapabilityCommand(Protocol):
    def receive(
        self, code: str, agent_key: str, data: NodeCapabilityReceived
    ) -> Awaitable[NodeCapabilityReceipt]: ...


class INodeCapabilityQuery(Protocol):
    def latest(self, node_id: int) -> Awaitable[NodeCapabilityLatest]: ...
    def history(
        self, node_id: int, data: NodeCapabilitySearch
    ) -> Awaitable[ServicePage[NodeCapabilityObservation]]: ...
