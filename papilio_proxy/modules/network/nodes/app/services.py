from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from papilio_proxy.modules.network.nodes.app.identity import node_email
from papilio_proxy.modules.network.nodes.interfaces import NodeRepository, PrivateNode
from papilio_proxy.modules.network.subscriptions.app.services import (
    AccessService,
    AccessUnavailable,
)

logger = logging.getLogger(__name__)


def _label(title: str) -> str:
    label = "🦋 " + title.strip()
    while len(label.encode()) > 120:
        label = label[:-1]
    return label or "Papilio"


class ProvisioningError(RuntimeError):
    """Keep the settled order retryable instead of claiming it was delivered."""


@dataclass(slots=True)
class NodeReconciler:
    repository: NodeRepository
    access: AccessService
    node: PrivateNode
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _last_report: float = 0.0

    async def run_once(self) -> None:
        if self._lock.locked():
            return
        async with self._lock:
            started = time.monotonic()
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
                    or issued.expires_at
                    != issued.snapshot.measured_at + timedelta(days=item.duration_days)
                ):
                    raise ProvisioningError("Node did not return a fresh zero-usage entitlement")
                await self.access.record_provisioned(
                    item.subscription_id,
                    issued.vless_link,
                    issued.vmess_link,
                    issued.snapshot.measured_at,
                )

            provisioned_at = time.monotonic()
            active = await self.repository.list_active_node_access()
            expected.update(node_email(item.access.subscription_id) for item in active)
            snapshots = {item.email: item for item in await self.node.usage()}
            fetched_at = time.monotonic()
            persisted = 0
            for item in active:
                access = item.access
                email = node_email(access.subscription_id)
                if (
                    access.expires_at <= datetime.now(UTC)
                    or access.uplink_bytes + access.downlink_bytes >= access.traffic_limit_bytes
                ):
                    await self.node.remove(email)
                    await self.repository.mark_expired(access.subscription_id)
                    continue
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
                fresh = (
                    access.last_measured_at is None
                    or snapshot.measured_at > access.last_measured_at
                )
                changed = (
                    snapshot.uplink_bytes != access.uplink_bytes
                    or snapshot.downlink_bytes != access.downlink_bytes
                )
                refresh_due = (
                    access.last_measured_at is None
                    or snapshot.measured_at - access.last_measured_at >= timedelta(minutes=1)
                )
                if fresh and (changed or refresh_due):
                    try:
                        exhausted = await self.access.record_usage(
                            access.subscription_id,
                            snapshot.uplink_bytes,
                            snapshot.downlink_bytes,
                            snapshot.measured_at,
                        )
                    except AccessUnavailable as exc:
                        raise ProvisioningError("Node counter cannot be persisted") from exc
                    persisted += 1
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

            finished = time.monotonic()
            if finished - started >= 1.5 or finished - self._last_report >= 60:
                log = logger.warning if finished - started >= 1.5 else logger.info
                log(
                    "Node reconciliation: active=%d pending=%d persisted=%d "
                    "provision_ms=%.0f fetch_ms=%.0f apply_ms=%.0f total_ms=%.0f",
                    len(active),
                    len(pending),
                    persisted,
                    (provisioned_at - started) * 1000,
                    (fetched_at - provisioned_at) * 1000,
                    (finished - fetched_at) * 1000,
                    (finished - started) * 1000,
                )
                self._last_report = finished
