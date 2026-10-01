from __future__ import annotations

import base64
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest import IsolatedAsyncioTestCase

from bot.models.node import ActiveNodeAccess, IssuedNodeLinks, NodeSnapshot, PendingProvision
from bot.services.access import AccessService
from bot.services.node import NodeReconciler, node_email
from tests.unit.test_access import MemoryAccessRepository

ORDER_ID = "123e4567-e89b-42d3-a456-426614174000"
VLESS = f"vless://{ORDER_ID}@node.example:8443?security=reality#Papilio"
VMESS = "vmess://" + base64.b64encode(
    json.dumps({"id": ORDER_ID, "add": "node.example"}).encode()
).decode()


class FakeRepository:
    def __init__(self, access: MemoryAccessRepository) -> None:
        self.access = access
        self.pending = [PendingProvision(ORDER_ID, 77, "آزمایش", 1000, 1)]
        self.expired: list[str] = []

    async def list_pending_paid(self, limit: int = 20) -> list[PendingProvision]:
        return self.pending[:limit]

    async def list_active_node_access(self) -> list[ActiveNodeAccess]:
        if self.access.access.subscription_id == ORDER_ID:
            return [ActiveNodeAccess(self.access.access, "آزمایش")]
        return []

    async def mark_expired(self, subscription_id: str) -> None:
        self.expired.append(subscription_id)


class FakeNode:
    def __init__(self) -> None:
        self.started = datetime.now(UTC).replace(microsecond=0)
        self.snapshot = NodeSnapshot(node_email(ORDER_ID), 0, 0, self.started, False)
        self.ensure_count = 0
        self.removed: list[str] = []
        self.heartbeats = 0

    async def heartbeat(self) -> None:
        self.heartbeats += 1

    async def ensure(
        self, *, identifier: str, email: str, label: str, quota_bytes: int,
        duration_days: int = 0, expires_at: datetime | None = None,
        baseline_uplink_bytes: int = 0, baseline_downlink_bytes: int = 0,
    ) -> IssuedNodeLinks:
        self.ensure_count += 1
        return IssuedNodeLinks(
            VLESS, VMESS, expires_at or self.started + timedelta(days=duration_days),
            self.snapshot,
        )

    async def usage(self) -> list[NodeSnapshot]:
        return [self.snapshot]

    async def remove(self, email: str) -> None:
        self.removed.append(email)


class NodeReconciliationTests(IsolatedAsyncioTestCase):
    async def test_paid_order_is_issued_once_then_usage_and_quota_are_reconciled(self) -> None:
        access_repo = MemoryAccessRepository()
        repository = FakeRepository(access_repo)
        node = FakeNode()
        reconciler = NodeReconciler(repository, AccessService(access_repo), node)

        await reconciler.run_once()
        self.assertEqual(node.ensure_count, 1)
        self.assertEqual(access_repo.access.subscription_id, ORDER_ID)
        self.assertEqual(access_repo.access.token.count("."), 0)
        repository.pending = []

        node.snapshot = replace(
            node.snapshot, uplink_bytes=800, downlink_bytes=100,
            measured_at=node.started + timedelta(seconds=1),
        )
        await reconciler.run_once()
        self.assertEqual(access_repo.access.traffic_used_bytes, 900)
        self.assertEqual(node.removed, [])

        node.snapshot = replace(
            node.snapshot, downlink_bytes=200,
            measured_at=node.started + timedelta(seconds=2), revoked=True,
        )
        await reconciler.run_once()
        self.assertEqual(access_repo.access.traffic_used_bytes, 1000)
        self.assertEqual(node.removed, [node_email(ORDER_ID)])
        self.assertEqual(repository.expired, [ORDER_ID])
        self.assertEqual(node.heartbeats, 3)

    async def test_unknown_node_user_is_revoked(self) -> None:
        access_repo = MemoryAccessRepository()
        repository = FakeRepository(access_repo)
        repository.pending = []
        node = FakeNode()
        node.snapshot = replace(node.snapshot, email="orphan")
        await NodeReconciler(repository, AccessService(access_repo), node).run_once()
        self.assertEqual(node.removed, ["orphan"])
