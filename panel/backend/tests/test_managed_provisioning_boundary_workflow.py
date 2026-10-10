"""Native ACK/lifecycle boundaries; leases are explicit persisted fixtures."""

import asyncio
from contextvars import Context
from datetime import UTC, datetime, timedelta

from papilio.infra.db.transaction import transaction
from papilio.security.crypto import hash_sha256
from sqlalchemy import text

from tests.test_managed_provisioning_lock_workflow import (
    ManagedProvisioningLockWorkflowFixture,
)


class ManagedProvisioningBoundaryWorkflowFixture(
    ManagedProvisioningLockWorkflowFixture
):
    async def lease_fixture(self, task_id):
        token = "synthetic_managed_task_lease_" + "a" * 32
        digest = await asyncio.to_thread(hash_sha256, token)
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    text(
                        "UPDATE tbl_provision_tasks SET state='leased',"
                        "attempts=1,claim_hash=:digest,claim_until=:until "
                        "WHERE id=:id"
                    ),
                    {
                        "id": task_id,
                        "digest": digest,
                        "until": datetime.now(UTC).replace(tzinfo=None)
                        + timedelta(seconds=120),
                    },
                )
        return token

    async def assert_boundary_state(self, subscription, task_id, expected):
        async with self.connection.uow() as fresh:
            task = await fresh.execute(
                text(
                    "SELECT state,attempts,last_outcome FROM "
                    "tbl_provision_tasks WHERE id=:id"
                ),
                {"id": task_id},
            )
            self.assertEqual(tuple(task.one()), expected)
            profile = await fresh.execute(
                text(
                    "SELECT applied_generation,applied_revision "
                    "FROM tbl_profiles WHERE id=(SELECT profile_id "
                    "FROM tbl_provision_tasks WHERE id=:id)"
                ),
                {"id": task_id},
            )
            self.assertEqual(tuple(profile.one()), (None, None))
            wallet = await fresh.execute(
                text(
                    "SELECT balance_rial FROM tbl_wallets "
                    "WHERE customer_id=:id"
                ),
                {"id": subscription["customer_id"]},
            )
            self.assertEqual(wallet.scalar_one(), 200000)
            grants = await fresh.execute(
                text(
                    "SELECT COUNT(*),SUM(allocated_bytes),SUM(is_closed) "
                    "FROM tbl_usage_grants WHERE subscription_id=:id"
                ),
                {"id": subscription["id"]},
            )
            self.assertEqual(tuple(grants.one()), (1, 1024, 0))


class ManagedProvisioningBoundaryWorkflowTest(
    ManagedProvisioningBoundaryWorkflowFixture
):
    async def test_failed_ack_customer_wait_does_not_hold_window_core(self):
        (
            subscription,
            node,
            body,
            path,
            _,
            task_id,
        ) = await self.setup_competing_work_item()
        token = await self.lease_fixture(task_id)
        window = acknowledgement = None
        try:
            async with self.connection.uow() as holder:
                async with transaction(holder):
                    await holder.execute(
                        text(
                            "SELECT id FROM tbl_nodes WHERE id=:id FOR UPDATE"
                        ),
                        {"id": node["node"]["id"]},
                    )
                    window = asyncio.create_task(
                        self.client.post(
                            path, headers=self.node_headers, json=body
                        ),
                        context=Context(),
                    )
                    self.assertTrue(await self.observe_wait("tbl_nodes"))
                    acknowledgement = asyncio.create_task(
                        self.client.post(
                            f"/v1/nodes/{node['node']['code']}"
                            f"/provisioning/{task_id}/acknowledge",
                            headers=self.node_headers,
                            json={
                                "claim_token": token,
                                "outcome": "failed",
                                "error_code": "synthetic_failure",
                            },
                        ),
                        context=Context(),
                    )
                    self.assertTrue(await self.observe_wait("tbl_customers"))
            issued, acknowledged = await asyncio.wait_for(
                asyncio.gather(window, acknowledgement), 12
            )
            self.assertEqual(issued.status_code, 200, issued.text)
            self.assertEqual(acknowledged.status_code, 200, acknowledged.text)
        finally:
            pending = [
                task for task in (window, acknowledgement) if task is not None
            ]
            for task in pending:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        await self.assert_boundary_state(
            subscription, task_id, ("failed", 1, "failed")
        )

    async def test_lifecycle_customer_wait_does_not_hold_window_subscription(
        self,
    ):
        (
            subscription,
            node,
            body,
            path,
            _,
            task_id,
        ) = await self.setup_competing_work_item()
        window = lifecycle = None
        try:
            async with self.connection.uow() as holder:
                async with transaction(holder):
                    await holder.execute(
                        text(
                            "SELECT id FROM tbl_nodes WHERE id=:id FOR UPDATE"
                        ),
                        {"id": node["node"]["id"]},
                    )
                    window = asyncio.create_task(
                        self.client.post(
                            path, headers=self.node_headers, json=body
                        ),
                        context=Context(),
                    )
                    self.assertTrue(await self.observe_wait("tbl_nodes"))
                    lifecycle = asyncio.create_task(
                        self.client.post(
                            f"/v1/admin/subscriptions/{subscription['id']}/check-lifecycle",
                            headers=self.headers,
                        ),
                        context=Context(),
                    )
                    self.assertTrue(await self.observe_wait("tbl_customers"))
            issued, checked = await asyncio.wait_for(
                asyncio.gather(window, lifecycle), 12
            )
            self.assertEqual(issued.status_code, 200, issued.text)
            self.assertEqual(checked.status_code, 200, checked.text)
            self.assertEqual(checked.json()["data"]["status"], "active")
        finally:
            pending = [
                task for task in (window, lifecycle) if task is not None
            ]
            for task in pending:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        await self.assert_boundary_state(
            subscription, task_id, ("queued", 0, None)
        )

    async def test_bound_task_ordinary_ack_is_blocked_when_flags_disabled(
        self,
    ):
        (
            subscription,
            node,
            body,
            path,
            _,
            task_id,
        ) = await self.setup_competing_work_item()
        token = await self.lease_fixture(task_id)
        issued = await self.client.post(
            path, headers=self.node_headers, json=body
        )
        self.assertEqual(issued.status_code, 200, issued.text)
        window_id = issued.json()["data"]["id"]
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    text(
                        "UPDATE tbl_managed_windows "
                        "SET provision_task_id=:task "
                        "WHERE id=:id"
                    ),
                    {"id": window_id, "task": task_id},
                )
        self.settings.managed_adapter = None
        self.settings.core_provisioning = None
        acknowledged = await self.client.post(
            f"/v1/nodes/{node['node']['code']}"
            f"/provisioning/{task_id}/acknowledge",
            headers=self.node_headers,
            json={"claim_token": token, "outcome": "applied"},
        )
        self.assertEqual(acknowledged.status_code, 409, acknowledged.text)
        await self.assert_boundary_state(
            subscription, task_id, ("leased", 1, None)
        )
        async with self.connection.uow() as fresh:
            request = await fresh.execute(
                text(
                    "SELECT state,activated_at FROM tbl_provision_requests "
                    "WHERE subscription_id=:id AND generation=0"
                ),
                {"id": subscription["id"]},
            )
            self.assertEqual(tuple(request.one()), ("dispatching", None))

    async def test_bound_task_failed_ack_preserves_pending_reservation(
        self,
    ):
        (
            subscription,
            node,
            body,
            path,
            _,
            task_id,
        ) = await self.setup_competing_work_item()
        token = await self.lease_fixture(task_id)
        issued = await self.client.post(
            path, headers=self.node_headers, json=body
        )
        self.assertEqual(issued.status_code, 200, issued.text)
        window_id = issued.json()["data"]["id"]
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    text(
                        "UPDATE tbl_managed_windows "
                        "SET provision_task_id=:task WHERE id=:id"
                    ),
                    {"id": window_id, "task": task_id},
                )
        self.settings.managed_adapter = None
        self.settings.core_provisioning = None
        acknowledged = await self.client.post(
            f"/v1/nodes/{node['node']['code']}"
            f"/provisioning/{task_id}/acknowledge",
            headers=self.node_headers,
            json={
                "claim_token": token,
                "outcome": "failed",
                "error_code": "synthetic_failure",
            },
        )
        self.assertEqual(acknowledged.status_code, 409, acknowledged.text)
        await self.assert_boundary_state(
            subscription, task_id, ("leased", 1, None)
        )
        async with self.connection.uow() as fresh:
            request = await fresh.execute(
                text(
                    "SELECT state,activated_at FROM tbl_provision_requests "
                    "WHERE subscription_id=:id AND generation=0"
                ),
                {"id": subscription["id"]},
            )
            self.assertEqual(tuple(request.one()), ("dispatching", None))

    async def test_ack_sees_binding_committed_during_customer_wait(self):
        (
            subscription,
            node,
            body,
            path,
            _,
            task_id,
        ) = await self.setup_competing_work_item()
        token = await self.lease_fixture(task_id)
        issued = await self.client.post(
            path, headers=self.node_headers, json=body
        )
        self.assertEqual(issued.status_code, 200, issued.text)
        window_id = issued.json()["data"]["id"]
        self.settings.managed_adapter = None
        self.settings.core_provisioning = None
        acknowledgement = None
        try:
            async with self.connection.uow() as holder:
                async with transaction(holder):
                    await holder.execute(
                        text(
                            "SELECT id FROM tbl_customers WHERE id IN "
                            "(SELECT customer_id FROM tbl_subscriptions "
                            "WHERE id=:id UNION SELECT payer_customer_id "
                            "FROM tbl_subscriptions WHERE id=:id) "
                            "ORDER BY id FOR UPDATE"
                        ),
                        {"id": subscription["id"]},
                    )
                    acknowledgement = asyncio.create_task(
                        self.client.post(
                            f"/v1/nodes/{node['node']['code']}"
                            f"/provisioning/{task_id}/acknowledge",
                            headers=self.node_headers,
                            json={"claim_token": token, "outcome": "applied"},
                        ),
                        context=Context(),
                    )
                    self.assertTrue(await self.observe_wait("tbl_customers"))
                    # Constructed storage binding after ACK's hint snapshot;
                    # this does not claim native paid admission was performed.
                    await holder.execute(
                        text(
                            "UPDATE tbl_managed_windows "
                            "SET provision_task_id=:task WHERE id=:id"
                        ),
                        {"id": window_id, "task": task_id},
                    )
            acknowledged = await asyncio.wait_for(acknowledgement, 12)
            self.assertEqual(acknowledged.status_code, 409, acknowledged.text)
        finally:
            if acknowledgement is not None:
                if not acknowledgement.done():
                    acknowledgement.cancel()
                await asyncio.gather(acknowledgement, return_exceptions=True)
        await self.assert_boundary_state(
            subscription, task_id, ("leased", 1, None)
        )
        async with self.connection.uow() as fresh:
            request = await fresh.execute(
                text(
                    "SELECT state,activated_at FROM tbl_provision_requests "
                    "WHERE subscription_id=:id AND generation=0"
                ),
                {"id": subscription["id"]},
            )
            self.assertEqual(tuple(request.one()), ("dispatching", None))
