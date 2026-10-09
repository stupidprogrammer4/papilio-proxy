import asyncio
import json
from contextvars import Context
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlmodel import col

from src.modules.network.core_runtime.infra.tables import (
    CoreRuntimeCommandTable,
    CoreRuntimeRevisionTable,
    CoreRuntimeStateTable,
)
from src.modules.sales.subscriptions.infra.tables import SubscriptionTable
from tests.test_fulfillment_workflow import FulfillmentWorkflowFixture
from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowFixture,
)


class CoreRuntimeWorkflowFixture(
    StaffAdministrationWorkflowFixture, FulfillmentWorkflowFixture
):
    async def setup_runtime(self):
        subscription, request, nodes, _ = await self.setup_sale(
            protocols=("vless_reality",)
        )
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        configuration = (await self.get("/v1/admin/network/configurations"))[
            "data"
        ][0]
        self.subscription_id = subscription["id"]
        self.node_code = nodes[0]["node"]["code"]
        self.node_headers = {"X-Papilio-Node-Key": nodes[0]["agent_key"]}
        self.runtime_path = (
            f"/v1/admin/network/cores/{configuration['core_id']}/runtime"
        )
        self.agent_path = f"/v1/nodes/{self.node_code}/runtime-commands"
        self.core_id = configuration["core_id"]
        return configuration

    async def state(self):
        result = await self.get(self.runtime_path)
        return result["data"]

    async def snapshot(self):
        state = await self.state()
        result = await self.post(
            self.runtime_path + "/revisions",
            {"expected_revision": state["revision"], "mode": "merged"},
        )
        return result

    async def enqueue(self, action, revision_id=None, key=None):
        state = await self.state()
        result = await self.post(
            self.runtime_path + "/commands",
            {
                "expected_revision": state["revision"],
                "action": action,
                "revision_id": revision_id,
                "request_key": key
                or f"{action}_{self.suffix}_{state['revision']}",
                "reason": "Native acceptance",
            },
        )
        return result

    async def runtime_claim(self, task):
        response = await self.client.post(
            f"{self.agent_path}/{task['id']}/claim", headers=self.node_headers
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    async def runtime_ack(
        self,
        claim,
        outcome="succeeded",
        observed=None,
        status="unknown",
        digest=None,
        error=None,
    ):
        result = await self.client.post(
            f"{self.agent_path}/{claim['command_id']}/acknowledge",
            headers=self.node_headers,
            json={
                "claim_token": claim["claim_token"],
                "outcome": outcome,
                "observed_revision_id": observed,
                "observed_status": status,
                "bundle_sha256": digest,
                "error_code": error,
            },
        )
        return result


class CoreRuntimeWorkflowTest(CoreRuntimeWorkflowFixture):
    async def test_native_runtime_revision_lease_ack_replay_and_scopes(
        self,
    ):
        await self.setup_runtime()
        initial = await self.state()
        self.assertIsNone(initial["id"])
        async with self.connection.uow() as uow:
            rows = await uow.execute(select(CoreRuntimeStateTable))
            self.assertEqual(list(rows.scalars()), [])
        revision = await self.snapshot()
        self.assertNotIn("encrypted_payload", revision)
        async with self.connection.uow() as uow:
            stored = (
                await uow.execute(
                    select(CoreRuntimeRevisionTable).where(
                        col(CoreRuntimeRevisionTable.id) == revision["id"]
                    )
                )
            ).scalar_one()
            self.assertNotIn("inbounds", stored.encrypted_payload)
        task = await self.enqueue(
            "validate", revision["id"], "validate_" + self.suffix
        )
        claim = await self.runtime_claim(task)
        self.assertTrue(claim["artifacts"])
        listed = await self.client.get(
            self.agent_path, headers=self.node_headers
        )
        self.assertEqual(listed.json()["data"], [])
        result = await self.runtime_ack(claim)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(
            (await self.state())["validated_revision_id"], revision["id"]
        )
        replay = await self.runtime_ack(claim)
        self.assertEqual(replay.status_code, 200)
        conflict = await self.runtime_ack(claim, status="stopped")
        self.assertEqual(conflict.status_code, 409)
        wrong = await self.client.post(
            f"{self.agent_path}/{task['id']}/claim",
            headers={"X-Papilio-Node-Key": "wrong"},
        )
        self.assertEqual(wrong.status_code, 401)
        blocked = await self.client.post(
            self.runtime_path + "/commands",
            headers=self.headers,
            json={
                "expected_revision": (await self.state())["revision"],
                "action": "apply",
                "revision_id": revision["id"],
                "request_key": "blocked_" + self.suffix,
                "reason": "Must stay stopped",
            },
        )
        self.assertEqual(blocked.status_code, 409)
        self.assertIn("runtime_start_disabled", blocked.text)
        repeated = await self.client.post(
            self.runtime_path + "/commands",
            headers=self.headers,
            json={
                "expected_revision": 1,
                "action": "validate",
                "revision_id": revision["id"],
                "request_key": "validate_" + self.suffix,
                "reason": "Native acceptance",
            },
        )
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["data"]["id"], task["id"])
        self.assertIsNotNone(revision["created_by_staff_id"])
        self.assertEqual(
            task["created_by_staff_id"], revision["created_by_staff_id"]
        )
        staff = await self.post(
            "/v1/admin/staff",
            {
                "username": "runtime_reader_" + self.suffix,
                "password": "fixture888",
                "is_active": True,
                "scopes": ["network:read", "network:create"],
            },
        )
        client, headers = await self.login_staff(
            staff["username"], "fixture888"
        )
        try:
            denied = await client.post(
                self.runtime_path + "/revisions",
                headers=headers,
                json={
                    "expected_revision": (await self.state())["revision"],
                    "mode": "merged",
                },
            )
            self.assertEqual(denied.status_code, 403)
        finally:
            await client.aclose()

    async def test_native_runtime_concurrent_command_and_claim_fencing(self):
        await self.setup_runtime()
        revision = await self.snapshot()
        state = await self.state()
        path = self.runtime_path + "/commands"
        first, second = await asyncio.gather(
            self.client.post(
                path,
                headers=self.headers,
                json={
                    "expected_revision": state["revision"],
                    "action": "validate",
                    "revision_id": revision["id"],
                    "request_key": "first_" + self.suffix,
                    "reason": "Concurrent first",
                },
            ),
            self.client.post(
                path,
                headers=self.headers,
                json={
                    "expected_revision": state["revision"],
                    "action": "validate",
                    "revision_id": revision["id"],
                    "request_key": "second_" + self.suffix,
                    "reason": "Concurrent second",
                },
            ),
        )
        self.assertEqual(
            sorted([first.status_code, second.status_code]), [200, 409]
        )
        task = (first if first.status_code == 200 else second).json()["data"]
        claims = await asyncio.gather(
            self.client.post(
                f"{self.agent_path}/{task['id']}/claim",
                headers=self.node_headers,
            ),
            self.client.post(
                f"{self.agent_path}/{task['id']}/claim",
                headers=self.node_headers,
            ),
        )
        self.assertEqual(sorted(row.status_code for row in claims), [200, 409])
        async with self.connection.uow() as uow:
            row = (
                await uow.execute(
                    select(CoreRuntimeCommandTable).where(
                        col(CoreRuntimeCommandTable.id) == task["id"]
                    )
                )
            ).scalar_one()
            self.assertEqual(row.attempts, 1)

    async def test_native_runtime_stale_ack_and_entitlement_safe_rollback(
        self,
    ):
        configuration = await self.setup_runtime()
        policy = self.settings.core_runtime
        assert policy is not None
        policy.allow_start = True
        revision = await self.snapshot()
        task = await self.enqueue("apply", revision["id"])
        claim = await self.runtime_claim(task)
        applied = await self.runtime_ack(
            claim,
            observed=revision["id"],
            status="running",
            digest=revision["bundle_sha256"],
        )
        self.assertEqual(applied.status_code, 200, applied.text)
        inventory = (
            await self.get(f"/v1/admin/network/cores/{self.core_id}")
        )["data"]
        self.assertEqual(inventory["application_status"], "applied")
        self.assertEqual(inventory["runtime"]["observed_status"], "running")
        self.assertEqual(
            inventory["runtime"]["applied_revision_id"], revision["id"]
        )
        changed = await self.client.put(
            f"/v1/admin/network/configurations/{configuration['id']}/server-json",
            headers=self.headers,
            json={
                "expected_revision": configuration["revision"],
                "reason": "Changed shared routing",
                "document": {
                    "mode": "managed",
                    "source": json.dumps(
                        {
                            "inbounds": [{"$papilio": "managed"}],
                            "dns": {"servers": ["9.9.9.9"]},
                        }
                    ),
                },
            },
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        rollback = await self.enqueue("rollback", revision["id"])
        rollback_claim = await self.runtime_claim(rollback)
        rolled = await self.runtime_ack(
            rollback_claim,
            observed=revision["id"],
            status="running",
            digest=revision["bundle_sha256"],
        )
        self.assertEqual(rolled.status_code, 200, rolled.text)
        current = await self.snapshot()
        interrupted = await self.enqueue("apply", current["id"])
        interrupted_claim = await self.runtime_claim(interrupted)
        failed = await self.runtime_ack(
            interrupted_claim,
            outcome="failed",
            observed=current["id"],
            status="stopped",
            digest=current["bundle_sha256"],
            error="runtime_recovery_required",
        )
        self.assertEqual(failed.status_code, 200, failed.text)
        self.assertEqual(
            (await self.state())["applied_revision_id"], revision["id"]
        )
        applying = await self.enqueue("apply", current["id"])
        applying_claim = await self.runtime_claim(applying)
        async with self.connection.uow() as uow:
            await uow.execute(
                update(SubscriptionTable)
                .where(col(SubscriptionTable.id) == self.subscription_id)
                .values(quota_bytes=1, used_bytes=1)
            )
            await uow.commit()
        stale = await self.runtime_ack(
            applying_claim,
            observed=current["id"],
            status="running",
            digest=current["bundle_sha256"],
        )
        self.assertEqual(stale.status_code, 200, stale.text)
        self.assertEqual(
            stale.json()["data"]["error_code"], "runtime_snapshot_stale"
        )
        state = await self.state()
        self.assertEqual(state["observed_status"], "unknown")
        self.assertEqual(state["applied_revision_id"], revision["id"])

    async def test_native_runtime_large_ciphertext_history_and_expired_lease(
        self,
    ):
        configuration = await self.setup_runtime()
        changed = await self.client.put(
            f"/v1/admin/network/configurations/{configuration['id']}/server-json",
            headers=self.headers,
            json={
                "expected_revision": configuration["revision"],
                "reason": "Large complete JSON snapshot",
                "document": {
                    "mode": "managed",
                    "source": json.dumps(
                        {
                            "inbounds": [{"$papilio": "managed"}],
                            "acceptance_metadata": "x" * 100000,
                        }
                    ),
                },
            },
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        revision = await self.snapshot()
        task = await self.enqueue("validate", revision["id"])
        claim = await self.runtime_claim(task)
        self.assertGreater(len(claim["artifacts"][0]["content"]), 65535)
        async with self.connection.uow() as uow:
            stored = (
                await uow.execute(
                    select(CoreRuntimeRevisionTable).where(
                        col(CoreRuntimeRevisionTable.id) == revision["id"]
                    )
                )
            ).scalar_one()
            self.assertGreater(len(stored.encrypted_payload), 65535)
            await uow.execute(
                update(CoreRuntimeCommandTable)
                .where(col(CoreRuntimeCommandTable.id) == task["id"])
                .values(
                    claim_until=datetime.now(UTC).replace(tzinfo=None)
                    - timedelta(seconds=1)
                )
            )
            await uow.commit()
        expired = await self.runtime_ack(claim)
        self.assertEqual(expired.status_code, 409)
        self.assertIn("runtime_lease_expired", expired.text)

    async def test_native_snapshot_export_uses_current_read_after_old_view(
        self,
    ):
        from papilio.infra.db.transaction import transaction
        from papilio.infra.db.uow import MySQLUnitOfWork

        from src.modules.network.configurations.infra.tables import (
            ConfigurationTable,
        )
        from src.modules.network.core_runtime.domain.dtos import (
            RuntimeRevisionCreate,
        )
        from src.modules.network.core_runtime.interfaces import (
            ICoreRuntimeCommand,
        )

        configuration = await self.setup_runtime()
        async with self.app.state.dishka_container() as scope:
            unit = await scope.get(MySQLUnitOfWork)
            command = await scope.get(ICoreRuntimeCommand)
            async with transaction(unit):
                original = await unit.execute(
                    select(ConfigurationTable).where(
                        col(ConfigurationTable.id) == configuration["id"]
                    )
                )
                self.assertEqual(original.scalar_one().revision, 1)
                changed = await asyncio.create_task(
                    self.client.put(
                        f"/v1/admin/network/configurations/{configuration['id']}/server-json",
                        headers=self.headers,
                        json={
                            "expected_revision": 1,
                            "reason": "Current read after old RR view",
                            "document": {
                                "mode": "managed",
                                "source": json.dumps(
                                    {
                                        "inbounds": [{"$papilio": "managed"}],
                                        "dns": {"servers": ["9.9.9.9"]},
                                    }
                                ),
                            },
                        },
                    ),
                    context=Context(),
                )
                self.assertEqual(changed.status_code, 200, changed.text)
                revision = await command.revision(
                    self.core_id,
                    RuntimeRevisionCreate(expected_revision=1, mode="merged"),
                )
                revision_id = revision.id
        task = await self.enqueue("validate", revision_id)
        claim = await self.runtime_claim(task)
        document = json.loads(claim["artifacts"][0]["content"])
        self.assertEqual(document.get("dns", {}).get("servers"), ["9.9.9.9"])

    async def test_populated_runtime_upgrade_and_downgrade_guard(self):
        from unittest.mock import patch

        from alembic import command
        from alembic.config import Config
        from sqlalchemy import text

        await self.setup_runtime()
        assert self.settings.db is not None
        migration = Config("alembic.ini")
        migration.set_main_option("sqlalchemy.url", self.settings.db.dsn)
        with patch.dict("os.environ", {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(
                command.downgrade, migration, "0044_customer_loyalty"
            )
            async with self.connection.uow() as unit:
                staff = (
                    await unit.execute(
                        text(
                            "SELECT id,username,is_active "
                            "FROM tbl_staff ORDER BY id"
                        )
                    )
                ).all()
                wallet = (
                    await unit.execute(
                        text(
                            "SELECT id,wallet_id,amount_rial,"
                            "balance_after_rial,reference "
                            "FROM tbl_wallet_entries ORDER BY id"
                        )
                    )
                ).all()
                subscriptions = (
                    await unit.execute(
                        text(
                            "SELECT id,customer_id,plan_id,quota_bytes,"
                            "price_rial,status "
                            "FROM tbl_subscriptions ORDER BY id"
                        )
                    )
                ).all()
            self.assertTrue(staff)
            self.assertTrue(wallet)
            self.assertTrue(subscriptions)
            await asyncio.to_thread(command.upgrade, migration, "head")
        async with self.connection.uow() as unit:
            fresh_staff = (
                await unit.execute(
                    text(
                        "SELECT id,username,is_active "
                        "FROM tbl_staff ORDER BY id"
                    )
                )
            ).all()
            fresh_wallet = (
                await unit.execute(
                    text(
                        "SELECT id,wallet_id,amount_rial,balance_after_rial,"
                        "reference FROM tbl_wallet_entries ORDER BY id"
                    )
                )
            ).all()
            fresh_subscriptions = (
                await unit.execute(
                    text(
                        "SELECT id,customer_id,plan_id,quota_bytes,"
                        "price_rial,status "
                        "FROM tbl_subscriptions ORDER BY id"
                    )
                )
            ).all()
        self.assertEqual(fresh_staff, staff)
        self.assertEqual(fresh_wallet, wallet)
        self.assertEqual(fresh_subscriptions, subscriptions)
        revision = await self.snapshot()
        with patch.dict("os.environ", {"PAPILIO_CONFIG": "config.yml.sample"}):
            with self.assertRaisesRegex(RuntimeError, "runtime history"):
                await asyncio.to_thread(
                    command.downgrade, migration, "0044_customer_loyalty"
                )
        async with self.connection.uow() as unit:
            version = (
                await unit.execute(
                    text("SELECT version_num FROM alembic_version")
                )
            ).scalar_one()
            preserved = (
                await unit.execute(
                    text(
                        "SELECT bundle_sha256 FROM tbl_core_runtime_revisions "
                        "WHERE id=:id"
                    ),
                    {"id": revision["id"]},
                )
            ).scalar_one()
            self.assertEqual(version, "0045_core_runtime")
            self.assertEqual(preserved, revision["bundle_sha256"])
