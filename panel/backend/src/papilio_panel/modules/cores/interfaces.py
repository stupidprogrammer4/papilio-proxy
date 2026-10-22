"""Core registration capabilities consumed by transports and service provisioning."""

from typing import Protocol
from uuid import UUID

from .domain import (
    CoreCreation,
    CorePage,
    CoreRead,
    CoreSearch,
    InboundCreation,
    InboundPage,
    InboundSearch,
    XrayInboundRead,
    XrayInboundRegistration,
    XrayRegistration,
)


class CoreStorage(Protocol):
    def register_xray(self, values: XrayRegistration) -> CoreCreation: ...
    def read(self, core_id: UUID, actor_id: int) -> CoreRead: ...
    def search(self, values: CoreSearch) -> CorePage: ...
    def register_inbound(self, values: XrayInboundRegistration) -> InboundCreation: ...
    def read_inbound(self, core_id: UUID, inbound_id: UUID, actor_id: int) -> XrayInboundRead: ...
    def search_inbounds(self, values: InboundSearch) -> InboundPage: ...


class CoreCapability(CoreStorage, Protocol):
    """Public application boundary; all methods enforce current owner permission."""
