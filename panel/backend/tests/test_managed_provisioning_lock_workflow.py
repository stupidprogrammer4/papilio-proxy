"""Real competing API locks with an explicitly constructed native work item."""

import asyncio
from contextvars import Context
from datetime import UTC, datetime

from papilio.infra.db.transaction import transaction
from sqlalchemy import text

from src.modules.network.provisioning.app.payloads import (
    ProvisionPayloadEncoding,
    ProvisionPayloadSource,
)
from src.modules.network.provisioning.domain.models import ProvisionTaskModel
from src.modules.network.provisioning.infra.mysql import (
    ProvisionTaskRepository,
)
from tests.test_managed_windows_workflow import ManagedWindowWorkflowFixture


class ManagedProvisioningLockWorkflowFixture(ManagedWindowWorkflowFixture):
    async def setup_competing_work_item(self):
        (
            subscription,
            node,
            _,
            body,
            window_path,
            configuration,
        ) = await self.setup_closed()
        policy = self.settings.managed_adapter
        assert policy is not None
        self.settings.managed_adapter = policy.model_copy(
            update={"window_mode": "reserved"}
        )
        async with self.connection.uow() as unit:
            request = await unit.execute(
                text(
                    "SELECT id FROM tbl_provision_requests "
                    "WHERE subscription_id=:id AND generation=0"
                ),
                {"id": subscription["id"]},
            )
            request_id = request.scalar_one()
            source = await unit.execute(
                text(
                    "SELECT p.id,p.encrypted_credentials,p.client_address,"
                    "c.encrypted_settings,c.listen_port FROM tbl_profiles p "
                    "JOIN tbl_configurations c ON c.id=p.configuration_id "
                    "WHERE p.id=:id"
                ),
                {"id": body["profile_id"]},
            )
            row = source.one()
            payload_source = ProvisionPayloadSource(
                configuration_id=configuration["id"],
                profile_id=row.id,
                core_id=configuration["core_id"],
                listen_port=row.listen_port,
                encrypted_settings=row.encrypted_settings,
                encrypted_credentials=row.encrypted_credentials,
                client_address=row.client_address,
            )
        encoded = await asyncio.to_thread(
            ProvisionPayloadEncoding().encode,
            payload_source,
            self.settings.configuration_encryption_key,
        )
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    text(
                        "UPDATE tbl_provision_requests "
                        "SET state='dispatching' "
                        "WHERE id=:id"
                    ),
                    {"id": request_id},
                )
                task = await ProvisionTaskRepository(unit).create(
                    ProvisionTaskModel(
                        configuration_revision=configuration["revision"],
                        encrypted_payload=encoded.ciphertext,
                        request_id=request_id,
                        configuration_id=configuration["id"],
                        profile_id=body["profile_id"],
                        node_id=node["node"]["id"],
                        available_at=datetime.now(UTC).replace(
                            tzinfo=None, microsecond=0
                        ),
                    )
                )
                task_id = task.id
        return subscription, node, body, window_path, request_id, task_id

    async def assert_preserved(self, subscription, task_id):
        async with self.connection.uow() as fresh:
            task = await fresh.execute(
                text(
                    "SELECT state,attempts FROM tbl_provision_tasks "
                    "WHERE id=:id"
                ),
                {"id": task_id},
            )
            self.assertEqual(tuple(task.one()), ("queued", 0))
            reservation = await fresh.execute(
                text(
                    "SELECT COUNT(*),SUM(allocated_bytes),SUM(is_closed) "
                    "FROM tbl_usage_grants WHERE subscription_id=:id"
                ),
                {"id": subscription["id"]},
            )
            self.assertEqual(tuple(reservation.one()), (1, 1024, 0))
            wallet = await fresh.execute(
                text(
                    "SELECT balance_rial FROM tbl_wallets "
                    "WHERE customer_id=:id"
                ),
                {"id": subscription["customer_id"]},
            )
            self.assertEqual(wallet.scalar_one(), 200000)
            profile = await fresh.execute(
                text(
                    "SELECT applied_generation,applied_revision "
                    "FROM tbl_profiles WHERE id=(SELECT profile_id "
                    "FROM tbl_provision_tasks WHERE id=:id)"
                ),
                {"id": task_id},
            )
            self.assertEqual(tuple(profile.one()), (None, None))


class ManagedProvisioningLockWorkflowTest(
    ManagedProvisioningLockWorkflowFixture
):
    async def test_prepare_customer_wait_does_not_hold_window_core(self):
        (
            subscription,
            node,
            body,
            window_path,
            request_id,
            task_id,
        ) = await self.setup_competing_work_item()
        window = prepare = None
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
                            window_path, headers=self.node_headers, json=body
                        ),
                        context=Context(),
                    )
                    self.assertTrue(await self.observe_wait("tbl_nodes"))
                    prepare = asyncio.create_task(
                        self.client.post(
                            f"/v1/admin/provisioning/{request_id}/prepare",
                            headers=self.headers,
                        ),
                        context=Context(),
                    )
                    self.assertTrue(await self.observe_wait("tbl_customers"))
            window_response, prepared = await asyncio.wait_for(
                asyncio.gather(window, prepare), 12
            )
            self.assertEqual(
                window_response.status_code, 200, window_response.text
            )
            self.assertEqual(prepared.status_code, 200, prepared.text)
        finally:
            pending = [task for task in (window, prepare) if task is not None]
            for task in pending:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        await self.assert_preserved(subscription, task_id)

    async def test_claim_customer_wait_does_not_hold_window_core(self):
        (
            subscription,
            node,
            body,
            window_path,
            _,
            task_id,
        ) = await self.setup_competing_work_item()
        window = claim = None
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
                            window_path, headers=self.node_headers, json=body
                        ),
                        context=Context(),
                    )
                    self.assertTrue(await self.observe_wait("tbl_nodes"))
                    claim = asyncio.create_task(
                        self.client.post(
                            f"/v1/nodes/{node['node']['code']}"
                            f"/provisioning/{task_id}/claim",
                            headers=self.node_headers,
                        ),
                        context=Context(),
                    )
                    self.assertTrue(await self.observe_wait("tbl_customers"))
            window_response, claimed = await asyncio.wait_for(
                asyncio.gather(window, claim), 12
            )
            self.assertEqual(
                window_response.status_code, 200, window_response.text
            )
            self.assertEqual(claimed.status_code, 409, claimed.text)
            self.assertIn("provision_runtime_pending", claimed.text)
        finally:
            pending = [task for task in (window, claim) if task is not None]
            for task in pending:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        await self.assert_preserved(subscription, task_id)
