import json

from tests.test_core_runtime_workflow import CoreRuntimeWorkflowFixture


class CoreProvisioningWorkflowFixture(CoreRuntimeWorkflowFixture):
    async def bridge_ensure(self):
        from src.modules.network.core_runtime.interfaces import (
            ICoreProvisioningCommand,
        )

        async with self.app.state.dishka_container() as scope:
            command = await scope.get(ICoreProvisioningCommand)
            result = await command.ensure(self.core_id)
        return result

    async def bridge_task(self):
        result = await self.client.get(
            f"/v1/nodes/{self.node_code}/provisioning",
            headers=self.node_headers,
            params={"core_id": self.core_id, "actionable": True},
        )
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()["data"][0]

    async def bridge_claim(self, task):
        response = await self.client.post(
            f"/v1/nodes/{self.node_code}/provisioning/{task['id']}/claim",
            headers=self.node_headers,
        )
        return response

    async def bridge_ack(self, claim, proof=True):
        body = {"claim_token": claim["claim_token"], "outcome": "applied"}
        if proof:
            body.update(
                runtime_revision_id=claim["installed_revision_id"],
                membership_sha256=claim["membership_sha256"],
            )
        response = await self.client.post(
            f"/v1/nodes/{self.node_code}/provisioning/{claim['task_id']}/acknowledge",
            headers=self.node_headers,
            json=body,
        )
        return response


class CoreProvisioningWorkflowTest(CoreProvisioningWorkflowFixture):
    async def test_cancelled_pending_profiles_leave_single_batch_and_runtime(
        self,
    ):
        assert self.settings.core_runtime is not None
        self.settings.core_runtime.allow_start = True
        configuration = await self.setup_runtime()
        revision = await self.snapshot()
        task = await self.enqueue("apply", revision["id"])
        claim = await self.runtime_claim(task)
        applied = await self.runtime_ack(
            claim,
            observed=revision["id"],
            status="running",
            digest=claim["bundle_sha256"],
        )
        self.assertEqual(applied.status_code, 200, applied.text)
        before = json.loads(claim["artifacts"][0]["content"])
        self.assertEqual(len(before["inbounds"][0]["settings"]["clients"]), 1)
        cancelled = await self.post(
            f"/v1/admin/subscriptions/{self.subscription_id}/provision-failed",
            {"reason": "Cancel paid pending generation safely"},
        )
        self.assertEqual(cancelled["status"], "pending_provision")
        single = await self.post(
            f"/v1/admin/network/configurations/{configuration['id']}/server-download"
        )
        batch = await self.post(
            "/v1/admin/network/configurations/server-downloads",
            {"configuration_ids": [configuration["id"]]},
        )
        with self.subTest(operation="single"):
            self.assertEqual(
                json.loads(single["content"])["inbounds"][0]["settings"][
                    "clients"
                ],
                [],
            )
        with self.subTest(operation="batch"):
            self.assertEqual(
                json.loads(batch[0]["content"])["inbounds"][0]["settings"][
                    "clients"
                ],
                [],
            )
        state = await self.state()
        restarted = await self.client.post(
            self.runtime_path + "/commands",
            headers=self.headers,
            json={
                "expected_revision": state["revision"],
                "action": "restart",
                "request_key": "cancelled_restart_" + self.suffix,
                "reason": "Must not resurrect cancelled credentials",
            },
        )
        self.assertEqual(restarted.status_code, 409, restarted.text)
        self.assertEqual(
            restarted.json()["error"]["message_code"], "runtime_snapshot_stale"
        )
        rollback = await self.client.post(
            self.runtime_path + "/commands",
            headers=self.headers,
            json={
                "expected_revision": state["revision"],
                "action": "rollback",
                "revision_id": revision["id"],
                "request_key": "cancelled_rollback_" + self.suffix,
                "reason": "Must not resurrect cancelled credentials",
            },
        )
        self.assertEqual(rollback.status_code, 409, rollback.text)
        self.assertEqual(
            rollback.json()["error"]["message_code"], "runtime_snapshot_stale"
        )

    async def test_installed_membership_paid_activation_proof_and_pause(self):
        from sqlalchemy import select
        from sqlmodel import col

        from src.modules.network.configurations.infra.tables import (
            ProfileTable,
        )
        from src.modules.network.provisioning.infra.tables import (
            ProvisionTaskTable,
        )

        assert self.settings.core_provisioning is not None
        assert self.settings.core_runtime is not None
        self.settings.core_provisioning.mode = "installed_only"
        self.settings.core_provisioning.observation_seconds = 600
        self.settings.core_runtime.allow_start = True
        await self.setup_runtime()
        profile_task = await self.bridge_task()
        premature = await self.bridge_claim(profile_task)
        self.assertEqual(premature.status_code, 409, premature.text)
        async with self.connection.uow() as unit:
            task = (
                await unit.execute(
                    select(ProvisionTaskTable).where(
                        col(ProvisionTaskTable.id) == profile_task["id"]
                    )
                )
            ).scalar_one()
            self.assertEqual(task.attempts, 0)
            self.assertEqual(task.state, "queued")
        first = await self.bridge_ensure()
        repeated = await self.bridge_ensure()
        self.assertEqual(first.command_id, repeated.command_id)
        self.assertEqual(repeated.state, "waiting")
        runtime = await self.runtime_claim({"id": first.command_id})
        history = await self.get(self.runtime_path + "/commands")
        leased_history = next(
            row
            for row in history["data"]
            if row["id"] == runtime["command_id"]
        )
        self.assertTrue(leased_history["created_at"].endswith("Z"))
        self.assertTrue(leased_history["claim_until"].endswith("Z"))
        revisions = await self.get(self.runtime_path + "/revisions")
        self.assertTrue(revisions["data"][0]["created_at"].endswith("Z"))
        membership = runtime["memberships"][0]
        self.assertEqual(membership["presence"], "present")
        self.assertEqual(
            membership["artifact_sha256"], runtime["artifacts"][0]["sha256"]
        )
        response = await self.runtime_ack(
            runtime,
            observed=runtime["revision_id"],
            status="running",
            digest=runtime["bundle_sha256"],
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue((await self.state())["last_observed_at"].endswith("Z"))
        async with self.connection.uow() as unit:
            profile = (
                await unit.execute(
                    select(ProfileTable).where(
                        col(ProfileTable.id) == profile_task["profile_id"]
                    )
                )
            ).scalar_one()
            self.assertIsNone(profile.applied_generation)
            self.assertIsNone(profile.applied_revision)
        leased = await self.bridge_claim(profile_task)
        self.assertEqual(leased.status_code, 200, leased.text)
        claim = leased.json()["data"]
        self.assertEqual(claim["membership"], membership)
        self.assertEqual(
            claim["installed_revision_id"], runtime["revision_id"]
        )
        self.assertEqual(
            claim["credential_sha256"], membership["credential_sha256"]
        )
        missing = await self.bridge_ack(claim, proof=False)
        self.assertEqual(missing.status_code, 409, missing.text)
        pause = await self.enqueue("stop")
        paused_ack = await self.bridge_ack(claim)
        self.assertEqual(paused_ack.status_code, 409, paused_ack.text)
        pause_claim = await self.runtime_claim(pause)
        pause_ack = await self.runtime_ack(
            pause_claim,
            observed=runtime["revision_id"],
            status="stopped",
            digest=runtime["bundle_sha256"],
        )
        self.assertEqual(pause_ack.status_code, 200, pause_ack.text)
        resume = await self.enqueue("restart")
        self.assertFalse((await self.state())["automation_paused"])
        resume_claim = await self.runtime_claim(resume)
        resume_ack = await self.runtime_ack(
            resume_claim,
            observed=runtime["revision_id"],
            status="running",
            digest=runtime["bundle_sha256"],
        )
        self.assertEqual(resume_ack.status_code, 200, resume_ack.text)
        acknowledged = await self.bridge_ack(claim)
        self.assertEqual(acknowledged.status_code, 200, acknowledged.text)
        replay = await self.bridge_ack(claim)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(
            acknowledged.json()["data"]["installed_revision_id"],
            runtime["revision_id"],
        )
        subscription = (
            await self.get(f"/v1/admin/subscriptions/{self.subscription_id}")
        )["data"]
        self.assertEqual(subscription["status"], "active")
        self.assertIsNotNone(subscription["expires_at"])
        self.assertEqual((await self.bridge_ensure()).state, "installed")
        restarted = await self.enqueue("restart")
        restarted_claim = await self.runtime_claim(restarted)
        restarted_ack = await self.runtime_ack(
            restarted_claim,
            observed=runtime["revision_id"],
            status="running",
            digest=runtime["bundle_sha256"],
        )
        self.assertEqual(restarted_ack.status_code, 200, restarted_ack.text)
        self.assertEqual(restarted_ack.json()["data"]["state"], "succeeded")
        stop = await self.enqueue("stop")
        self.assertTrue((await self.state())["automation_paused"])
        blocked = await self.bridge_ensure()
        self.assertEqual(blocked.reason_code, "runtime_automation_paused")
        stop_claim = await self.runtime_claim(stop)
        stopped = await self.runtime_ack(
            stop_claim,
            observed=runtime["revision_id"],
            status="stopped",
            digest=runtime["bundle_sha256"],
        )
        self.assertEqual(stopped.status_code, 200, stopped.text)
        self.assertEqual(
            (await self.bridge_ensure()).reason_code,
            "runtime_automation_paused",
        )
        replay_after_stop = await self.bridge_ack(claim)
        self.assertEqual(
            replay_after_stop.status_code, 200, replay_after_stop.text
        )

    async def test_coalesced_stale_recovery_observation_and_core_fencing(self):
        import asyncio
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import select, update
        from sqlmodel import col

        from src.modules.network.core_runtime.infra.tables import (
            CoreRuntimeCommandTable,
            CoreRuntimeStateTable,
        )

        assert self.settings.core_provisioning is not None
        assert self.settings.core_runtime is not None
        self.settings.core_provisioning.mode = "installed_only"
        self.settings.core_provisioning.observation_seconds = 600
        self.settings.core_runtime.allow_start = True
        configuration = await self.setup_runtime()
        decisions = await asyncio.gather(
            self.bridge_ensure(), self.bridge_ensure()
        )
        self.assertEqual(decisions[0].command_id, decisions[1].command_id)
        self.assertEqual(
            {row.state for row in decisions}, {"queued", "waiting"}
        )
        first_id = decisions[0].command_id
        changed = await self.client.put(
            f"/v1/admin/network/configurations/{configuration['id']}/server-json",
            headers=self.headers,
            json={
                "expected_revision": 1,
                "reason": "New topology supersedes pending capture",
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
        current = await self.bridge_ensure()
        self.assertNotEqual(current.command_id, first_id)
        async with self.connection.uow() as unit:
            old = (
                await unit.execute(
                    select(CoreRuntimeCommandTable).where(
                        col(CoreRuntimeCommandTable.id) == first_id
                    )
                )
            ).scalar_one()
            self.assertEqual(old.state, "failed")
            self.assertEqual(old.error_code, "runtime_superseded")
        runtime = await self.runtime_claim({"id": current.command_id})
        ack = await self.runtime_ack(
            runtime,
            observed=runtime["revision_id"],
            status="running",
            digest=runtime["bundle_sha256"],
        )
        self.assertEqual(ack.status_code, 200, ack.text)
        from src.modules.network.provisioning.infra.tables import (
            ProvisionRequestTable,
        )

        async with self.connection.uow() as unit:
            request = (
                await unit.execute(select(ProvisionRequestTable))
            ).scalar_one()
            request_id = request.id
        prepared, installed = await asyncio.gather(
            self.post(f"/v1/admin/provisioning/{request_id}/prepare"),
            self.bridge_ensure(),
        )
        self.assertEqual(prepared["state"], "dispatching")
        self.assertEqual(installed.state, "installed")
        async with self.connection.uow() as unit:
            await unit.execute(
                update(CoreRuntimeStateTable)
                .where(col(CoreRuntimeStateTable.core_id) == self.core_id)
                .values(
                    last_observed_at=datetime.now(UTC).replace(tzinfo=None)
                    - timedelta(seconds=601)
                )
            )
            await unit.commit()
        profile_task = await self.bridge_task()
        stale_observation = await self.bridge_claim(profile_task)
        self.assertEqual(
            stale_observation.status_code, 409, stale_observation.text
        )
        observe = await self.bridge_ensure()
        observed_claim = await self.runtime_claim({"id": observe.command_id})
        self.assertEqual(observed_claim["action"], "reconcile")
        self.assertEqual(observed_claim["reconcile_mode"], "observe")
        stopped = await self.runtime_ack(
            observed_claim,
            observed=runtime["revision_id"],
            status="stopped",
            digest=runtime["bundle_sha256"],
        )
        self.assertEqual(stopped.status_code, 200, stopped.text)
        self.assertEqual(stopped.json()["data"]["state"], "succeeded")
        recovered = await self.bridge_ensure()
        self.assertEqual(recovered.state, "queued")
        self.assertNotEqual(recovered.revision_id, runtime["revision_id"])
        recovery_claim = await self.runtime_claim({"id": recovered.command_id})
        recovered_ack = await self.runtime_ack(
            recovery_claim,
            observed=recovered.revision_id,
            status="running",
            digest=recovery_claim["bundle_sha256"],
        )
        self.assertEqual(recovered_ack.status_code, 200, recovered_ack.text)
        self.assertEqual((await self.bridge_ensure()).state, "installed")
        manual = await self.enqueue("validate", recovered.revision_id)
        protected = await self.bridge_ensure()
        self.assertEqual(protected.command_id, manual["id"])
        self.assertEqual(protected.state, "waiting")

    async def test_fair_bounded_scan_visits_blocked_cores(self):
        from src.modules.network.core_runtime.interfaces import (
            ICoreProvisioningQuery,
        )

        assert self.settings.core_provisioning is not None
        self.settings.core_provisioning.mode = "installed_only"
        self.settings.core_provisioning.batch_size = 1
        _, request, _, _ = await self.setup_sale()
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        async with self.app.state.dishka_container() as scope:
            query = await scope.get(ICoreProvisioningQuery)
            first = await query.due_core_ids(500)
        self.assertEqual(len(first), 1)
        self.core_id = first[0]
        self.assertEqual(
            (await self.bridge_ensure()).reason_code, "runtime_start_disabled"
        )
        async with self.app.state.dishka_container() as scope:
            query = await scope.get(ICoreProvisioningQuery)
            second = await query.due_core_ids(500)
        self.assertEqual(len(second), 1)
        self.assertNotEqual(first, second)

    async def test_disabled_node_blocks_auto_start_without_spending_attempts(
        self,
    ):
        assert self.settings.core_runtime is not None
        assert self.settings.core_provisioning is not None
        self.settings.core_runtime.allow_start = True
        self.settings.core_provisioning.mode = "installed_only"
        configuration = await self.setup_runtime()
        disabled = await self.client.patch(
            f"/v1/admin/network/nodes/{configuration['node_id']}/enabled",
            headers=self.headers,
            json={"enabled": False},
        )
        self.assertEqual(disabled.status_code, 200, disabled.text)
        decision = await self.bridge_ensure()
        self.assertEqual(decision.state, "blocked")
        self.assertEqual(decision.reason_code, "runtime_node_disabled")
        commands = await self.get(self.runtime_path + "/commands")
        self.assertEqual(commands["data"], [])
        task = await self.bridge_task()
        self.assertEqual(task["attempts"], 0)

    async def test_populated_0045_membership_upgrade_preserves_legacy_history(
        self,
    ):
        import asyncio
        from unittest.mock import patch

        from alembic import command
        from alembic.config import Config
        from sqlalchemy import text

        assert self.settings.core_runtime is not None
        assert self.settings.core_provisioning is not None
        self.settings.core_runtime.allow_start = True
        await self.setup_runtime()
        revision = await self.snapshot()
        task = await self.enqueue("apply", revision["id"])
        runtime = await self.runtime_claim(task)
        self.assertIsNone(runtime["memberships"])
        applied = await self.runtime_ack(
            runtime,
            observed=revision["id"],
            status="running",
            digest=runtime["bundle_sha256"],
        )
        self.assertEqual(applied.status_code, 200, applied.text)
        assert self.settings.db is not None
        migration = Config("alembic.ini")
        migration.set_main_option("sqlalchemy.url", self.settings.db.dsn)
        with patch.dict("os.environ", {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(
                command.downgrade, migration, "0045_core_runtime"
            )
        async with self.connection.uow() as unit:
            version = (
                await unit.execute(
                    text("SELECT version_num FROM alembic_version")
                )
            ).scalar_one()
            history = (
                await unit.execute(
                    text(
                        "SELECT id,core_id,bundle_sha256,encrypted_payload "
                        "FROM tbl_core_runtime_revisions"
                    )
                )
            ).one()
            staff_count = (
                await unit.execute(text("SELECT COUNT(*) FROM tbl_staff"))
            ).scalar_one()
            wallet_balance = (
                await unit.execute(
                    text("SELECT SUM(balance_rial) FROM tbl_wallets")
                )
            ).scalar_one()
            profile_count = (
                await unit.execute(text("SELECT COUNT(*) FROM tbl_profiles"))
            ).scalar_one()
        self.assertEqual(version, "0045_core_runtime")
        self.assertEqual(history.id, revision["id"])
        with patch.dict("os.environ", {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(
                command.upgrade, migration, "0046_core_memberships"
            )
        async with self.connection.uow() as unit:
            upgraded = (
                await unit.execute(
                    text(
                        "SELECT id,core_id,bundle_sha256,encrypted_payload,"
                        "encrypted_memberships,membership_sha256 "
                        "FROM tbl_core_runtime_revisions"
                    )
                )
            ).one()
            task_proof = (
                await unit.execute(
                    text(
                        "SELECT installed_revision_id,membership_sha256,"
                        "ack_sha256 FROM tbl_provision_tasks"
                    )
                )
            ).one()
            state = (
                await unit.execute(
                    text(
                        "SELECT automation_paused,last_observed_at "
                        "FROM tbl_core_runtime_states"
                    )
                )
            ).one()
            self.assertEqual(
                (
                    await unit.execute(text("SELECT COUNT(*) FROM tbl_staff"))
                ).scalar_one(),
                staff_count,
            )
            self.assertEqual(
                (
                    await unit.execute(
                        text("SELECT SUM(balance_rial) FROM tbl_wallets")
                    )
                ).scalar_one(),
                wallet_balance,
            )
            self.assertEqual(
                (
                    await unit.execute(
                        text("SELECT COUNT(*) FROM tbl_profiles")
                    )
                ).scalar_one(),
                profile_count,
            )
        self.assertEqual(tuple(upgraded)[:4], tuple(history))
        self.assertEqual(tuple(upgraded)[4:], (None, None))
        self.assertEqual(tuple(task_proof), (None, None, None))
        self.assertFalse(state.automation_paused)
        self.assertIsNone(state.last_observed_at)
        with patch.dict("os.environ", {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(command.upgrade, migration, "head")
        self.settings.core_provisioning.mode = "installed_only"
        self.settings.core_provisioning.observation_seconds = 600
        current = await self.state()
        observe = await self.post(
            self.runtime_path + "/commands",
            {
                "expected_revision": current["revision"],
                "action": "reconcile",
                "reconcile_mode": "observe",
                "request_key": "legacy_observe_" + self.suffix,
                "reason": "Observe legacy installation without membership",
            },
        )
        observe_claim = await self.runtime_claim(observe)
        observed = await self.runtime_ack(
            observe_claim,
            observed=revision["id"],
            status="running",
            digest=runtime["bundle_sha256"],
        )
        self.assertEqual(observed.status_code, 200, observed.text)
        legacy_task = await self.bridge_task()
        unavailable = await self.bridge_claim(legacy_task)
        self.assertEqual(unavailable.status_code, 409, unavailable.text)
        self.assertEqual(
            unavailable.json()["error"]["message_code"],
            "provision_runtime_membership_unavailable",
        )
        new_revision = await self.snapshot()
        self.assertIsNotNone(new_revision["membership_sha256"])
        with patch.dict("os.environ", {"PAPILIO_CONFIG": "config.yml.sample"}):
            with self.assertRaisesRegex(
                RuntimeError, "preserve installed membership history"
            ):
                await asyncio.to_thread(
                    command.downgrade, migration, "0045_core_runtime"
                )
        async with self.connection.uow() as unit:
            self.assertEqual(
                (
                    await unit.execute(
                        text("SELECT version_num FROM alembic_version")
                    )
                ).scalar_one(),
                "0046_core_memberships",
            )
            self.assertEqual(
                (
                    await unit.execute(
                        text("SELECT SUM(balance_rial) FROM tbl_wallets")
                    )
                ).scalar_one(),
                wallet_balance,
            )
            self.assertEqual(
                (
                    await unit.execute(text("SELECT COUNT(*) FROM tbl_staff"))
                ).scalar_one(),
                staff_count,
            )
            self.assertEqual(
                (
                    await unit.execute(
                        text("SELECT COUNT(*) FROM tbl_core_runtime_revisions")
                    )
                ).scalar_one(),
                2,
            )

    async def test_unchanged_automatic_snapshot_retry_budget_and_backoff(self):
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import update
        from sqlmodel import col

        from src.modules.network.core_runtime.infra.tables import (
            CoreRuntimeCommandTable,
        )

        assert self.settings.core_provisioning is not None
        assert self.settings.core_runtime is not None
        self.settings.core_provisioning.mode = "installed_only"
        self.settings.core_provisioning.max_attempts = 2
        self.settings.core_provisioning.retry_seconds = 20
        self.settings.core_runtime.allow_start = True
        await self.setup_runtime()
        first = await self.bridge_ensure()
        first_claim = await self.runtime_claim({"id": first.command_id})
        failed = await self.runtime_ack(
            first_claim,
            outcome="failed",
            status="stopped",
            error="core_validation_failed",
        )
        self.assertEqual(failed.status_code, 200, failed.text)
        backing_off = await self.bridge_ensure()
        self.assertEqual(backing_off.state, "blocked")
        self.assertEqual(backing_off.reason_code, "runtime_retry_pending")
        self.assertEqual(backing_off.revision_id, first.revision_id)
        async with self.connection.uow() as unit:
            await unit.execute(
                update(CoreRuntimeCommandTable)
                .where(col(CoreRuntimeCommandTable.id) == first.command_id)
                .values(
                    updated_at=datetime.now(UTC).replace(tzinfo=None)
                    - timedelta(seconds=21)
                )
            )
            await unit.commit()
        second = await self.bridge_ensure()
        self.assertEqual(second.state, "queued")
        self.assertEqual(second.revision_id, first.revision_id)
        second_claim = await self.runtime_claim({"id": second.command_id})
        failed_again = await self.runtime_ack(
            second_claim,
            outcome="failed",
            status="stopped",
            error="core_validation_failed",
        )
        self.assertEqual(failed_again.status_code, 200, failed_again.text)
        exhausted = await self.bridge_ensure()
        self.assertEqual(
            exhausted.reason_code, "runtime_provision_attempts_exhausted"
        )
        revisions = await self.get(self.runtime_path + "/revisions")
        self.assertEqual(revisions["meta"]["pager"]["total_items"], 1)
        configuration = (await self.get("/v1/admin/network/configurations"))[
            "data"
        ][0]
        changed = await self.client.put(
            f"/v1/admin/network/configurations/{configuration['id']}/server-json",
            headers=self.headers,
            json={
                "expected_revision": 1,
                "reason": "New topology has a new retry budget",
                "document": {
                    "mode": "managed",
                    "source": json.dumps(
                        {
                            "inbounds": [{"$papilio": "managed"}],
                            "dns": {"servers": ["1.1.1.1"]},
                        }
                    ),
                },
            },
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        renewed = await self.bridge_ensure()
        self.assertEqual(renewed.state, "queued")
        self.assertNotEqual(renewed.revision_id, first.revision_id)

        self.settings.core_provisioning.max_attempts = 1
        await self.runtime_claim({"id": renewed.command_id})
        async with self.connection.uow() as unit:
            await unit.execute(
                update(CoreRuntimeCommandTable)
                .where(col(CoreRuntimeCommandTable.id) == renewed.command_id)
                .values(
                    claim_until=datetime.now(UTC).replace(tzinfo=None)
                    - timedelta(seconds=1)
                )
            )
            await unit.commit()
        from src.modules.network.core_runtime.interfaces import (
            ICoreRuntimeCommand,
        )

        async with self.app.state.dishka_container() as scope:
            runtime = await scope.get(ICoreRuntimeCommand)
            recovered = await runtime.recover(renewed.command_id)
        self.assertEqual(recovered.state, "failed")
        self.assertEqual(recovered.attempts, 1)
        still_exhausted = await self.bridge_ensure()
        self.assertEqual(
            still_exhausted.reason_code,
            "runtime_provision_attempts_exhausted",
        )
        self.assertEqual(still_exhausted.revision_id, renewed.revision_id)
