from datetime import datetime
from typing import Protocol

from papilio_proxy.modules.network.nodes.domain.entities import (
    ActiveNodeAccess,
    IssuedNodeLinks,
    NodeSnapshot,
    PendingProvision,
)


class NodeRepository(Protocol):
    async def list_pending_paid(self, limit: int = 20) -> list[PendingProvision]: ...
    async def list_active_node_access(self) -> list[ActiveNodeAccess]: ...
    async def mark_expired(self, subscription_id: str) -> None: ...


class PrivateNode(Protocol):
    async def heartbeat(self) -> None: ...
    async def ensure(
        self,
        *,
        identifier: str,
        email: str,
        label: str,
        quota_bytes: int,
        duration_days: int = 0,
        expires_at: datetime | None = None,
        baseline_uplink_bytes: int = 0,
        baseline_downlink_bytes: int = 0,
    ) -> IssuedNodeLinks: ...
    async def usage(self) -> list[NodeSnapshot]: ...
    async def remove(self, email: str) -> None: ...
