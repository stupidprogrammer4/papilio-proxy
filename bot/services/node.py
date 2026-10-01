from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Protocol

from bot.models.node import ActiveNodeAccess, IssuedNodeLinks, NodeSnapshot, PendingProvision
from bot.services.access import AccessService, AccessUnavailable


def node_email(subscription_id: str) -> str:
    """An opaque, deterministic Xray accounting key for one paid order."""
    return "ent-" + sha256(subscription_id.encode()).hexdigest()[:48]


def _label(title: str) -> str:
    label = "🦋 " + title.strip()
    while len(label.encode()) > 120:
        label = label[:-1]
    return label or "Papilio"


class NodeRepository(Protocol):
    async def list_pending_paid(self, limit: int = 20) -> list[PendingProvision]: ...
    async def list_active_node_access(self) -> list[ActiveNodeAccess]: ...
    async def mark_expired(self, subscription_id: str) -> None: ...


class PrivateNode(Protocol):
    async def heartbeat(self) -> None: ...
    async def ensure(
        self, *, identifier: str, email: str, label: str, quota_bytes: int,
        duration_days: int = 0, expires_at: datetime | None = None,
        baseline_uplink_bytes: int = 0, baseline_downlink_bytes: int = 0,
    ) -> IssuedNodeLinks: ...
    async def usage(self) -> list[NodeSnapshot]: ...
    async def remove(self, email: str) -> None: ...


class ProvisioningError(RuntimeError):
    """Keep the settled order retryable instead of claiming it was delivered."""


@dataclass(slots=True)
class NodeReconciler:
    repository: NodeRepository
    access: AccessService
    node: PrivateNode
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def run_once(self) -> None:
        if self._lock.locked():
            return
        async with self._lock:
            await self.node.heartbeat()
            pending = await self.repository.list_pending_paid()
            expected = {node_email(item.subscription_id) for item in pending}
            for item in pending:
                issued = await self.node.ensure(
                    identifier=item.subscription_id,
                    email=node_email(item.subscription_id),
                    label=_label(item.title),
                    quota_bytes=item.traffic_limit_bytes,
                    duration_days=item.duration_days,
                )
                if (
                    issued.snapshot.email != node_email(item.subscription_id)
                    or issued.snapshot.revoked
                    or issued.snapshot.uplink_bytes != 0
                    or issued.snapshot.downlink_bytes != 0
                    or issued.expires_at != issued.snapshot.measured_at
                    + timedelta(days=item.duration_days)
                ):
                    raise ProvisioningError("Node did not return a fresh zero-usage entitlement")
                await self.access.record_provisioned(
                    item.subscription_id,
                    issued.vless_link,
                    issued.vmess_link,
                    issued.snapshot.measured_at,
                )

            active = await self.repository.list_active_node_access()
            expected.update(node_email(item.access.subscription_id) for item in active)
            snapshots = {item.email: item for item in await self.node.usage()}
            for item in active:
                access = item.access
                email = node_email(access.subscription_id)
                snapshot = snapshots.get(email)
                if snapshot is None:
                    issued = await self.node.ensure(
                        identifier=access.subscription_id,
                        email=email,
                        label=_label(item.title),
                        quota_bytes=access.traffic_limit_bytes,
                        expires_at=access.expires_at,
                        baseline_uplink_bytes=access.uplink_bytes,
                        baseline_downlink_bytes=access.downlink_bytes,
                    )
                    snapshot = issued.snapshot
                if snapshot.email != email:
                    raise ProvisioningError("Node returned the wrong account counter")
                if (
                    access.last_measured_at is None
                    or snapshot.measured_at > access.last_measured_at
                ):
                    try:
                        exhausted = await self.access.record_usage(
                            access.subscription_id,
                            snapshot.uplink_bytes,
                            snapshot.downlink_bytes,
                            snapshot.measured_at,
                        )
                    except AccessUnavailable as exc:
                        raise ProvisioningError("Node counter cannot be persisted") from exc
                else:
                    exhausted = (
                        snapshot.uplink_bytes + snapshot.downlink_bytes
                        >= access.traffic_limit_bytes
                    )
                if snapshot.revoked or access.expires_at <= datetime.now(UTC) or exhausted:
                    await self.node.remove(email)
                    await self.repository.mark_expired(access.subscription_id)

            for email, snapshot in snapshots.items():
                if email not in expected and not snapshot.revoked:
                    await self.node.remove(email)
