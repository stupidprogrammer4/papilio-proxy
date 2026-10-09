import json
from datetime import UTC, datetime

from src.modules.network.core_runtime.domain.usage import CoreUsageCapacity
from tests.test_core_provisioning_workflow import (
    CoreProvisioningWorkflowFixture,
)


class CoreUsageWorkflowTest(CoreProvisioningWorkflowFixture):
    async def open_usage_grant(self, claim, epoch, task, key):
        allocation = {
            "profile_id": task["profile_id"],
            "generation": 0,
            "request_key": key + self.suffix,
            "requested_bytes": claim["usage"]["profiles"][0]["grant_bytes"],
            "installed_revision_id": claim["revision_id"],
            "usage_sha256": claim["usage_sha256"],
            "process_epoch": epoch,
        }
        response = await self.client.post(
            self.usage_path, headers=self.node_headers, json=allocation
        )
        self.assertEqual(response.status_code, 200, response.text)
        return allocation, response.json()["data"]

    async def finalize_usage_grant(self, grant, epoch):
        report = {
            "event_id": "native_final_" + self.suffix,
            "sequence": 1,
            "upload_bytes": 100,
            "download_bytes": 200,
            "sampled_at": datetime.now(UTC).isoformat(),
            "final": True,
            "process_epoch": epoch,
        }
        response = await self.client.post(
            f"{self.usage_path}/{grant['id']}/reports",
            headers=self.node_headers,
            json=report,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return report

    async def shared_core_open_grants(self, mode):
        import asyncio

        await self.setup_usage()
        assert self.settings.core_usage is not None
        self.settings.core_usage.mode = mode
        claim, epoch, task = await self.install_usage()
        allocation, grant = await self.open_usage_grant(
            claim, epoch, task, "shared_"
        )
        candidate = await self.snapshot()
        state = await self.state()
        self.assertEqual(
            state["start_blocked_reason"], "runtime_usage_unresolved_grants"
        )
        self.assertNotIn("restart", state["allowed_actions"])
        attempts = await asyncio.gather(
            *(
                self.client.post(
                    self.runtime_path + "/commands",
                    headers=self.headers,
                    json={
                        "expected_revision": state["revision"],
                        "action": action,
                        "revision_id": candidate["id"],
                        "reconcile_mode": "restore"
                        if action == "reconcile"
                        else None,
                        "request_key": action + "_shared_" + self.suffix,
                        "reason": "Open grants preserve installed customers",
                    },
                )
                for action in ("apply", "restart", "rollback", "reconcile")
            )
        )
        self.assertEqual(
            [response.status_code for response in attempts], [409] * 4
        )
        self.assertTrue(
            all(
                "runtime_usage_unresolved_grants" in response.text
                for response in attempts
            )
        )
        unchanged = await self.state()
        self.assertEqual(unchanged["revision"], state["revision"])
        self.assertEqual(
            unchanged["applied_revision_id"], claim["revision_id"]
        )
        self.assertEqual(unchanged["observed_status"], "running")
        validate = await self.enqueue("validate", candidate["id"])
        validated = await self.runtime_claim(validate)
        response = await self.client.post(
            f"{self.agent_path}/{validated['command_id']}/acknowledge",
            headers=self.node_headers,
            json={
                "claim_token": validated["claim_token"],
                "outcome": "succeeded",
                "observed_revision_id": claim["revision_id"],
                "observed_status": "running",
                "bundle_sha256": claim["bundle_sha256"],
                "usage_sha256": claim["usage_sha256"],
                "process_epoch": epoch,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        subscription = (
            await self.get(f"/v1/admin/subscriptions/{self.subscription_id}")
        )["data"]
        pending = await self.post(
            "/v1/admin/subscriptions",
            {
                "customer_id": subscription["customer_id"],
                "plan_id": subscription["plan_id"],
                "purchase_key": "shared_paid_" + self.suffix,
            },
        )
        requests = await self.get(
            f"/v1/admin/provisioning?subscription_id={pending['id']}"
        )
        request = requests["data"][0]
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        decision = await self.bridge_ensure()
        self.assertEqual(decision.state, "blocked")
        self.assertEqual(
            decision.reason_code, "runtime_usage_unresolved_grants"
        )
        paid = (await self.get(f"/v1/admin/subscriptions/{pending['id']}"))[
            "data"
        ]
        self.assertEqual(paid["status"], "pending_provision")
        queued = await self.bridge_task()
        self.assertEqual(queued["request_id"], request["id"])
        self.assertEqual(queued["attempts"], 0)
        replay = await self.client.post(
            self.usage_path, headers=self.node_headers, json=allocation
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["data"]["id"], grant["id"])
        await self.finalize_usage_grant(grant, epoch)
        ready = await self.bridge_ensure()
        self.assertEqual(ready.state, "queued")
        self.assertIsNotNone(ready.command_id)

    async def test_native_observe_open_grants_preserve_paid_orders(self):
        await self.shared_core_open_grants("observe")

    async def test_native_polled_stop_open_grants_preserve_paid_orders(self):
        await self.shared_core_open_grants("polled_stop")

    async def test_native_queued_and_leased_replacement_blocks_new_allocation(
        self,
    ):
        await self.setup_usage()
        claim, epoch, task = await self.install_usage()
        allocation, grant = await self.open_usage_grant(
            claim, epoch, task, "before_"
        )
        await self.finalize_usage_grant(grant, epoch)
        candidate = await self.snapshot()
        command = await self.enqueue("apply", candidate["id"])
        fresh = {**allocation, "request_key": "queued_" + self.suffix}
        queued = await self.client.post(
            self.usage_path, headers=self.node_headers, json=fresh
        )
        self.assertEqual(queued.status_code, 409, queued.text)
        self.assertIn("runtime_usage_replacement_pending", queued.text)
        replay = await self.client.post(
            self.usage_path, headers=self.node_headers, json=allocation
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["data"]["id"], grant["id"])
        leased = await self.runtime_claim(command)
        fresh["request_key"] = "leased_" + self.suffix
        denied = await self.client.post(
            self.usage_path, headers=self.node_headers, json=fresh
        )
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertIn("runtime_usage_replacement_pending", denied.text)
        history = await self.get(
            f"/v1/admin/usage/grants?subscription_id={self.subscription_id}"
        )
        self.assertEqual(history["meta"]["pager"]["total_items"], 1)
        state = await self.state()
        self.assertEqual(state["applied_revision_id"], claim["revision_id"])
        self.assertEqual(state["observed_process_epoch"], epoch)
        self.assertEqual(leased["command_id"], command["id"])

    async def test_native_open_legacy_grant_claim_preserves_attempt(
        self,
    ):
        from datetime import timedelta

        from sqlalchemy import select, update
        from sqlmodel import col

        from src.modules.network.core_runtime.infra.tables import (
            CoreRuntimeCommandTable,
        )
        from src.modules.network.usage.infra.tables import UsageGrantTable

        await self.setup_usage()
        claim, _, task = await self.install_usage()
        candidate = await self.snapshot()
        command = await self.enqueue("apply", candidate["id"])
        assert self.settings.core_usage is not None
        self.settings.core_usage.mode = "disabled"
        legacy = await self.client.post(
            self.usage_path,
            headers=self.node_headers,
            json={
                "profile_id": task["profile_id"],
                "generation": 0,
                "request_key": "legacy_open_" + self.suffix,
                "requested_bytes": claim["usage"]["profiles"][0][
                    "grant_bytes"
                ],
            },
        )
        self.assertEqual(legacy.status_code, 200, legacy.text)
        self.settings.core_usage.mode = "observe"
        grant = legacy.json()["data"]
        async with self.connection.uow() as unit:
            await unit.execute(
                update(UsageGrantTable)
                .where(col(UsageGrantTable.id) == grant["id"])
                .values(
                    valid_until=datetime.now(UTC).replace(tzinfo=None)
                    - timedelta(seconds=1)
                )
            )
            await unit.commit()
        denied = await self.client.post(
            f"{self.agent_path}/{command['id']}/claim",
            headers=self.node_headers,
        )
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertIn("runtime_usage_unresolved_grants", denied.text)
        history = await self.get(self.runtime_path + "/commands")
        current = next(
            row for row in history["data"] if row["id"] == command["id"]
        )
        async with self.connection.uow() as unit:
            attempts = (
                await unit.execute(
                    select(col(CoreRuntimeCommandTable.attempts)).where(
                        col(CoreRuntimeCommandTable.id) == command["id"]
                    )
                )
            ).scalar_one()
        self.assertEqual(attempts, 0)
        self.assertEqual(current["state"], "queued")
        self.assertEqual(
            (await self.state())["applied_revision_id"], claim["revision_id"]
        )

    async def test_native_success_ack_rechecks_policy_window_open_grants(self):
        from sqlalchemy import select
        from sqlmodel import col

        from src.modules.network.usage.infra.tables import UsageGrantTable

        await self.setup_usage()
        installed, _, task = await self.install_usage()
        candidate = await self.snapshot()
        command = await self.enqueue("apply", candidate["id"])
        lease = await self.runtime_claim(command)
        assert self.settings.core_usage is not None
        self.settings.core_usage.mode = "disabled"
        legacy = await self.client.post(
            self.usage_path,
            headers=self.node_headers,
            json={
                "profile_id": task["profile_id"],
                "generation": 0,
                "request_key": "ack_window_" + self.suffix,
                "requested_bytes": installed["usage"]["profiles"][0][
                    "grant_bytes"
                ],
            },
        )
        self.assertEqual(legacy.status_code, 200, legacy.text)
        self.settings.core_usage.mode = "observe"
        acknowledgement = {
            "claim_token": lease["claim_token"],
            "outcome": "succeeded",
            "observed_revision_id": lease["revision_id"],
            "observed_status": "running",
            "bundle_sha256": lease["bundle_sha256"],
            "usage_sha256": lease["usage_sha256"],
            "process_epoch": "b" * 32,
        }
        path = f"{self.agent_path}/{lease['command_id']}/acknowledge"
        result = await self.client.post(
            path, headers=self.node_headers, json=acknowledgement
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["data"]["state"], "failed")
        self.assertEqual(
            result.json()["data"]["error_code"],
            "runtime_usage_unresolved_grants",
        )
        state = await self.state()
        self.assertEqual(
            state["applied_revision_id"], installed["revision_id"]
        )
        self.assertEqual(state["observed_status"], "unknown")
        self.assertIsNone(state["observed_process_epoch"])
        replay = await self.client.post(
            path, headers=self.node_headers, json=acknowledgement
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["data"], result.json()["data"])
        self.assertEqual((await self.state())["revision"], state["revision"])
        async with self.connection.uow() as unit:
            closed = (
                await unit.execute(
                    select(col(UsageGrantTable.is_closed)).where(
                        col(UsageGrantTable.id) == legacy.json()["data"]["id"]
                    )
                )
            ).scalar_one()
        self.assertFalse(closed)

    async def setup_usage(self):
        assert self.settings.core_provisioning is not None
        assert self.settings.core_runtime is not None
        self.settings.core_provisioning.mode = "installed_only"
        self.settings.core_provisioning.observation_seconds = 600
        self.settings.core_runtime.allow_start = True
        configuration = await self.setup_runtime()
        self.settings.core_usage = CoreUsageCapacity(
            mode="observe",
            stats_ports={self.core_id: 18080},
            max_profiles=100,
            max_document_bytes=1000000,
            observation_seconds=600,
        )
        self.usage_path = f"/v1/nodes/{self.node_code}/usage/grants"
        return configuration

    async def install_usage(self):
        first = await self.bridge_ensure()
        claim = await self.runtime_claim({"id": first.command_id})
        epoch = "a" * 32
        body = {
            "claim_token": claim["claim_token"],
            "outcome": "succeeded",
            "observed_revision_id": claim["revision_id"],
            "observed_status": "running",
            "bundle_sha256": claim["bundle_sha256"],
            "usage_sha256": claim["usage_sha256"],
            "process_epoch": epoch,
        }
        response = await self.client.post(
            f"{self.agent_path}/{claim['command_id']}/acknowledge",
            headers=self.node_headers,
            json=body,
        )
        self.assertEqual(response.status_code, 200, response.text)
        profile_task = await self.bridge_task()
        leased = await self.bridge_claim(profile_task)
        self.assertEqual(leased.status_code, 200, leased.text)
        response = await self.bridge_ack(leased.json()["data"])
        self.assertEqual(response.status_code, 200, response.text)
        return claim, epoch, profile_task

    async def test_native_usage_capability_epoch_binding_and_replay(self):
        await self.setup_usage()
        claim, epoch, profile_task = await self.install_usage()
        document = json.loads(claim["artifacts"][0]["content"])
        self.assertEqual(document["api"]["tag"], "papilio-stats-api")
        self.assertEqual(document["routing"]["domainStrategy"], "IPOnDemand")
        self.assertEqual(
            document["routing"]["rules"][0]["inboundTag"],
            ["papilio-stats-api"],
        )
        capability = claim["usage"]
        self.assertEqual(
            capability["profiles"][0]["profile_id"], profile_task["profile_id"]
        )
        counter = capability["profiles"][0]["counter_identity"]
        self.assertEqual(
            document["inbounds"][0]["settings"]["clients"][0]["email"], counter
        )
        allocation = {
            "profile_id": profile_task["profile_id"],
            "generation": 0,
            "request_key": "usage_" + self.suffix,
            "requested_bytes": capability["profiles"][0]["grant_bytes"],
        }
        missing = await self.client.post(
            self.usage_path, headers=self.node_headers, json=allocation
        )
        self.assertEqual(missing.status_code, 409, missing.text)
        allocation.update(
            installed_revision_id=claim["revision_id"],
            usage_sha256=claim["usage_sha256"],
            process_epoch="b" * 32,
        )
        stale = await self.client.post(
            self.usage_path, headers=self.node_headers, json=allocation
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        allocation["process_epoch"] = epoch
        response = await self.client.post(
            self.usage_path, headers=self.node_headers, json=allocation
        )
        self.assertEqual(response.status_code, 200, response.text)
        grant = response.json()["data"]
        replay = await self.client.post(
            self.usage_path, headers=self.node_headers, json=allocation
        )
        self.assertEqual(replay.json()["data"]["id"], grant["id"])
        report = {
            "event_id": "report_" + self.suffix,
            "sequence": 1,
            "upload_bytes": 100,
            "download_bytes": 200,
            "sampled_at": datetime.now(UTC).isoformat(),
            "final": False,
            "process_epoch": "b" * 32,
        }
        report_path = f"{self.usage_path}/{grant['id']}/reports"
        mismatch = await self.client.post(
            report_path, headers=self.node_headers, json=report
        )
        self.assertEqual(mismatch.status_code, 409, mismatch.text)
        report["process_epoch"] = epoch
        reported = await self.client.post(
            report_path, headers=self.node_headers, json=report
        )
        self.assertEqual(reported.status_code, 200, reported.text)
        duplicate = await self.client.post(
            report_path, headers=self.node_headers, json=report
        )
        self.assertEqual(
            duplicate.json()["data"]["id"], reported.json()["data"]["id"]
        )
        subscription = (
            await self.get(f"/v1/admin/subscriptions/{self.subscription_id}")
        )["data"]
        self.assertEqual(subscription["used_bytes"], 300)
        await self.enqueue("stop")
        allocation["request_key"] = "paused_" + self.suffix
        paused = await self.client.post(
            self.usage_path, headers=self.node_headers, json=allocation
        )
        self.assertEqual(paused.status_code, 409, paused.text)

    async def test_unknown_peer_blocks_native_start_until_node_stop_ack(self):
        configuration = await self.setup_usage()
        revision = await self.snapshot()
        peer = await self.post(
            f"/v1/admin/network/nodes/{configuration['node_id']}/cores",
            {
                "code": "unknown_" + self.suffix,
                "label": "Unknown runtime",
                "kind": "xray",
            },
        )
        state = await self.state()
        denied = await self.client.post(
            self.runtime_path + "/commands",
            headers=self.headers,
            json={
                "expected_revision": state["revision"],
                "action": "apply",
                "revision_id": revision["id"],
                "request_key": "guard_" + self.suffix,
                "reason": "Unknown peer must be stopped first",
            },
        )
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertIn("runtime_usage_peer_not_stopped", denied.text)
        peer_path = f"/v1/admin/network/cores/{peer['id']}/runtime"
        peer_state = (await self.get(peer_path))["data"]
        stop = await self.post(
            peer_path + "/commands",
            {
                "expected_revision": peer_state["revision"],
                "action": "stop",
                "request_key": "stop_unknown_" + self.suffix,
                "reason": "Native node stop acknowledgement",
            },
        )
        claim = await self.runtime_claim(stop)
        stopped = await self.runtime_ack(claim, status="stopped")
        self.assertEqual(stopped.status_code, 200, stopped.text)
        admitted = await self.enqueue("apply", revision["id"])
        self.assertEqual(admitted["revision_id"], revision["id"])

    async def test_native_usage_observation_never_revives_or_finalizes_epoch(
        self,
    ):
        from datetime import timedelta

        from sqlalchemy import select, update
        from sqlmodel import col

        from src.modules.network.core_runtime.infra.tables import (
            CoreRuntimeStateTable,
        )
        from src.modules.network.usage.infra.tables import UsageGrantTable

        await self.setup_usage()
        claim, epoch, task = await self.install_usage()
        before = await self.state()
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
        allocation = {
            "profile_id": task["profile_id"],
            "generation": 0,
            "request_key": "observe_grant_" + self.suffix,
            "requested_bytes": claim["usage"]["profiles"][0]["grant_bytes"],
            "installed_revision_id": claim["revision_id"],
            "usage_sha256": claim["usage_sha256"],
            "process_epoch": epoch,
        }
        expired = await self.client.post(
            self.usage_path, headers=self.node_headers, json=allocation
        )
        self.assertEqual(expired.status_code, 409, expired.text)
        path = f"/v1/nodes/{self.node_code}/usage-observations/{self.core_id}"
        observation = {
            "runtime_revision_id": claim["revision_id"],
            "usage_sha256": claim["usage_sha256"],
            "membership_sha256": claim["membership_sha256"],
            "process_epoch": epoch,
            "observed_status": "running",
        }
        refreshed = await self.client.post(
            path, headers=self.node_headers, json=observation
        )
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assertTrue(
            refreshed.json()["data"]["last_observed_at"].endswith("Z")
        )
        allocated = await self.client.post(
            self.usage_path, headers=self.node_headers, json=allocation
        )
        self.assertEqual(allocated.status_code, 200, allocated.text)
        grant = allocated.json()["data"]
        observation["observed_status"] = "stopped"
        stopped = await self.client.post(
            path, headers=self.node_headers, json=observation
        )
        self.assertEqual(stopped.status_code, 200, stopped.text)
        after = await self.state()
        self.assertEqual(after["revision"], before["revision"])
        self.assertEqual(
            after["applied_revision_id"], before["applied_revision_id"]
        )
        self.assertEqual(after["observed_process_epoch"], epoch)
        self.assertFalse(after["automation_paused"])
        async with self.connection.uow() as unit:
            closed = (
                await unit.execute(
                    select(col(UsageGrantTable.is_closed)).where(
                        col(UsageGrantTable.id) == grant["id"]
                    )
                )
            ).scalar_one()
        self.assertFalse(closed)
        observation["observed_status"] = "running"
        revived = await self.client.post(
            path, headers=self.node_headers, json=observation
        )
        self.assertEqual(revived.status_code, 409, revived.text)
        self.assertIn("runtime_usage_observation_stopped", revived.text)

    async def test_native_all_reserved_ports_and_unsafe_egress_rejection(self):
        configuration = await self.setup_usage()
        first = await self.snapshot()
        peer = await self.post(
            f"/v1/admin/network/nodes/{configuration['node_id']}/cores",
            {
                "code": "mapped_" + self.suffix,
                "label": "Mapped stats peer",
                "kind": "xray",
            },
        )
        assert self.settings.core_usage is not None
        self.settings.core_usage.stats_ports[peer["id"]] = 18081
        peer_path = f"/v1/admin/network/cores/{peer['id']}/runtime"
        stop = await self.post(
            peer_path + "/commands",
            {
                "expected_revision": 1,
                "action": "stop",
                "request_key": "guard_stop_" + self.suffix,
                "reason": "Native isolated peer stop",
            },
        )
        stopped = await self.runtime_ack(
            await self.runtime_claim(stop), status="stopped"
        )
        self.assertEqual(stopped.status_code, 200, stopped.text)
        state = await self.state()
        stale = await self.client.post(
            self.runtime_path + "/commands",
            headers=self.headers,
            json={
                "expected_revision": state["revision"],
                "action": "apply",
                "revision_id": first["id"],
                "request_key": "old_guard_" + self.suffix,
                "reason": "New reserved port invalidates old guard",
            },
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertIn("runtime_snapshot_stale", stale.text)
        current = await self.snapshot()
        validate = await self.enqueue("validate", current["id"])
        claim = await self.runtime_claim(validate)
        document = json.loads(claim["artifacts"][0]["content"])
        self.assertEqual(
            claim["usage"]["artifacts"][0]["protected_ports"], [18080, 18081]
        )

        self.assertEqual(
            document["routing"]["rules"][0]["inboundTag"],
            ["papilio-stats-api"],
        )
        guard = document["routing"]["rules"][1]
        self.assertEqual(guard["port"], "18080,18081")
        self.assertNotIn("ip", guard)
        self.assertNotIn("domain", guard)
        acknowledged = await self.runtime_ack(claim, status="stopped")
        self.assertEqual(acknowledged.status_code, 200, acknowledged.text)
        changed = await self.client.put(
            f"/v1/admin/network/configurations/{configuration['id']}/server-json",
            headers=self.headers,
            json={
                "expected_revision": 1,
                "reason": "Unsafe custom redirect must remain offline",
                "document": {
                    "mode": "managed",
                    "source": json.dumps(
                        {
                            "inbounds": [{"$papilio": "managed"}],
                            "outbounds": [
                                {
                                    "tag": "direct",
                                    "protocol": "freedom",
                                    "settings": {
                                        "redirect": "127.0.0.1:18081"
                                    },
                                }
                            ],
                        }
                    ),
                },
            },
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        state = await self.state()
        captured = await self.client.post(
            self.runtime_path + "/revisions",
            headers=self.headers,
            json={"expected_revision": state["revision"], "mode": "merged"},
        )
        self.assertEqual(captured.status_code, 409, captured.text)
        self.assertIn("runtime_usage_egress_unavailable", captured.text)

    async def test_populated_0047_usage_upgrade_and_downgrade_guard(self):
        import asyncio
        from unittest.mock import patch

        from alembic import command
        from alembic.config import Config
        from sqlalchemy import text

        await self.setup_runtime()
        legacy = await self.snapshot()
        assert self.settings.db is not None
        migration = Config("alembic.ini")
        migration.set_main_option("sqlalchemy.url", self.settings.db.dsn)
        with patch.dict("os.environ", {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(
                command.downgrade,
                migration,
                "0047_subscription_notice_context",
            )
        async with self.connection.uow() as unit:
            staff = (await unit.execute(text("SELECT * FROM tbl_staff"))).all()
            wallets = (
                await unit.execute(text("SELECT * FROM tbl_wallet_entries"))
            ).all()
            notices = (
                await unit.execute(text("SELECT * FROM tbl_notifications"))
            ).all()
            revisions = (
                await unit.execute(
                    text("SELECT * FROM tbl_core_runtime_revisions")
                )
            ).all()
        self.assertTrue(staff)
        self.assertTrue(wallets)
        self.assertEqual(revisions[0].id, legacy["id"])
        with patch.dict("os.environ", {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(
                command.upgrade, migration, "0048_core_usage_proof"
            )
        async with self.connection.uow() as unit:
            self.assertEqual(
                (await unit.execute(text("SELECT * FROM tbl_staff"))).all(),
                staff,
            )
            self.assertEqual(
                (
                    await unit.execute(
                        text("SELECT * FROM tbl_wallet_entries")
                    )
                ).all(),
                wallets,
            )
            self.assertEqual(
                (
                    await unit.execute(text("SELECT * FROM tbl_notifications"))
                ).all(),
                notices,
            )
            upgraded = (
                await unit.execute(
                    text("SELECT * FROM tbl_core_runtime_revisions")
                )
            ).all()
            self.assertEqual(tuple(upgraded[0])[:-2], tuple(revisions[0]))
            self.assertIsNone(upgraded[0].encrypted_usage)
            self.assertIsNone(upgraded[0].usage_sha256)
        assert self.settings.core_provisioning is not None
        self.settings.core_provisioning.mode = "installed_only"
        self.settings.core_usage = CoreUsageCapacity(
            mode="observe",
            stats_ports={self.core_id: 18080},
            max_profiles=100,
            max_document_bytes=1000000,
            observation_seconds=600,
        )
        protected = await self.snapshot()
        self.assertIsNotNone(protected["usage_sha256"])
        with patch.dict("os.environ", {"PAPILIO_CONFIG": "config.yml.sample"}):
            with self.assertRaisesRegex(RuntimeError, "usage provenance"):
                await asyncio.to_thread(
                    command.downgrade,
                    migration,
                    "0047_subscription_notice_context",
                )
        async with self.connection.uow() as unit:
            version = (
                await unit.execute(
                    text("SELECT version_num FROM alembic_version")
                )
            ).scalar_one()
            proof = (
                await unit.execute(
                    text(
                        "SELECT usage_sha256,encrypted_usage "
                        "FROM tbl_core_runtime_revisions WHERE id=:id"
                    ),
                    {"id": protected["id"]},
                )
            ).one()
        self.assertEqual(version, "0048_core_usage_proof")
        self.assertEqual(proof.usage_sha256, protected["usage_sha256"])
        self.assertTrue(proof.encrypted_usage)

    async def test_native_two_core_capture_and_start_admission_concurrency(
        self,
    ):
        import asyncio

        configuration = await self.setup_usage()
        peer = await self.post(
            f"/v1/admin/network/nodes/{configuration['node_id']}/cores",
            {
                "code": "concurrent_" + self.suffix,
                "label": "Peer",
                "kind": "xray",
            },
        )
        await self.post(
            "/v1/admin/network/configurations",
            {
                "node_id": configuration["node_id"],
                "core_id": peer["id"],
                "listen_port": 18082,
                "label": "Concurrent peer inbound",
                "options": {
                    "protocol": "vless_reality",
                    "listen_address": "0.0.0.0",
                    "server_name": "example.com",
                    "target_port": 443,
                },
            },
        )
        assert self.settings.core_usage is not None
        self.settings.core_usage.stats_ports[peer["id"]] = 18081
        peer_path = f"/v1/admin/network/cores/{peer['id']}/runtime"
        stop = await self.post(
            peer_path + "/commands",
            {
                "expected_revision": 1,
                "action": "stop",
                "request_key": "concurrent_stop_" + self.suffix,
                "reason": "Native known stopped peer",
            },
        )
        stopped = await self.runtime_ack(
            await self.runtime_claim(stop), status="stopped"
        )
        self.assertEqual(stopped.status_code, 200, stopped.text)
        own_stop = await self.enqueue("stop")
        own_stopped = await self.runtime_ack(
            await self.runtime_claim(own_stop), status="stopped"
        )
        self.assertEqual(own_stopped.status_code, 200, own_stopped.text)
        own_state = await self.state()
        peer_state = (await self.get(peer_path))["data"]
        captures = await asyncio.wait_for(
            asyncio.gather(
                self.client.post(
                    self.runtime_path + "/revisions",
                    headers=self.headers,
                    json={
                        "expected_revision": own_state["revision"],
                        "mode": "merged",
                    },
                ),
                self.client.post(
                    peer_path + "/revisions",
                    headers=self.headers,
                    json={
                        "expected_revision": peer_state["revision"],
                        "mode": "merged",
                    },
                ),
            ),
            timeout=20,
        )
        self.assertEqual(
            [response.status_code for response in captures], [200, 200]
        )
        own_state = await self.state()
        peer_state = (await self.get(peer_path))["data"]
        starts = await asyncio.wait_for(
            asyncio.gather(
                self.client.post(
                    self.runtime_path + "/commands",
                    headers=self.headers,
                    json={
                        "expected_revision": own_state["revision"],
                        "action": "apply",
                        "revision_id": captures[0].json()["data"]["id"],
                        "request_key": "concurrent_own_" + self.suffix,
                        "reason": "Concurrent start reservation",
                    },
                ),
                self.client.post(
                    peer_path + "/commands",
                    headers=self.headers,
                    json={
                        "expected_revision": peer_state["revision"],
                        "action": "apply",
                        "revision_id": captures[1].json()["data"]["id"],
                        "request_key": "concurrent_peer_" + self.suffix,
                        "reason": "Concurrent start reservation",
                    },
                ),
            ),
            timeout=20,
        )
        self.assertEqual(
            sorted(response.status_code for response in starts), [200, 409]
        )
        refusal = next(
            response for response in starts if response.status_code == 409
        )
        self.assertIn("runtime_usage_peer_start_pending", refusal.text)

    async def test_native_node_reservations_current_after_old_read_view(self):
        import asyncio
        from contextvars import Context

        from papilio.infra.db.transaction import transaction
        from papilio.infra.db.uow import MySQLUnitOfWork
        from sqlalchemy import select
        from sqlmodel import col

        from src.modules.network.core_runtime.domain.dtos import (
            RuntimeRevisionCreate,
        )
        from src.modules.network.core_runtime.interfaces import (
            ICoreRuntimeCommand,
        )
        from src.modules.network.cores.infra.tables import CoreTable

        configuration = await self.setup_usage()
        async with self.app.state.dishka_container() as scope:
            unit = await scope.get(MySQLUnitOfWork)
            command = await scope.get(ICoreRuntimeCommand)
            async with transaction(unit):
                old = await unit.execute(
                    select(col(CoreTable.id)).where(
                        col(CoreTable.node_id) == configuration["node_id"]
                    )
                )
                original_ids = set(old.scalars())
                peer = await asyncio.create_task(
                    self.client.post(
                        f"/v1/admin/network/nodes/{configuration['node_id']}/cores",
                        headers=self.headers,
                        json={
                            "code": "current_" + self.suffix,
                            "label": "Current peer",
                            "kind": "xray",
                        },
                    ),
                    context=Context(),
                )
                self.assertEqual(peer.status_code, 200, peer.text)
                peer_id = peer.json()["data"]["id"]
                self.assertNotIn(peer_id, original_ids)
                assert self.settings.core_usage is not None
                self.settings.core_usage.stats_ports[peer_id] = 18081
                revision = await command.revision(
                    self.core_id,
                    RuntimeRevisionCreate(expected_revision=1, mode="merged"),
                )
                revision_id = revision.id
        validate = await self.enqueue("validate", revision_id)
        claim = await self.runtime_claim(validate)
        self.assertEqual(
            claim["usage"]["artifacts"][0]["protected_ports"], [18080, 18081]
        )

    async def test_native_running_peer_payload_budget_is_configurable(self):
        configuration = await self.setup_usage()
        peer = await self.post(
            f"/v1/admin/network/nodes/{configuration['node_id']}/cores",
            {
                "code": "budget_" + self.suffix,
                "label": "Budget peer",
                "kind": "xray",
            },
        )
        await self.post(
            "/v1/admin/network/configurations",
            {
                "node_id": configuration["node_id"],
                "core_id": peer["id"],
                "listen_port": 18082,
                "label": "Budget peer inbound",
                "options": {
                    "protocol": "vless_reality",
                    "listen_address": "0.0.0.0",
                    "server_name": "example.com",
                    "target_port": 443,
                },
            },
        )
        assert self.settings.core_usage is not None
        self.settings.core_usage.stats_ports[peer["id"]] = 18081
        peer_path = f"/v1/admin/network/cores/{peer['id']}/runtime"
        stop = await self.post(
            peer_path + "/commands",
            {
                "expected_revision": 1,
                "action": "stop",
                "request_key": "budget_stop_" + self.suffix,
                "reason": "Known stopped native peer",
            },
        )
        response = await self.runtime_ack(
            await self.runtime_claim(stop), status="stopped"
        )
        self.assertEqual(response.status_code, 200, response.text)
        await self.install_usage()
        peer_state = (await self.get(peer_path))["data"]
        revision = await self.post(
            peer_path + "/revisions",
            {"expected_revision": peer_state["revision"], "mode": "merged"},
        )
        peer_state = (await self.get(peer_path))["data"]
        request = {
            "expected_revision": peer_state["revision"],
            "action": "apply",
            "revision_id": revision["id"],
            "request_key": "budget_apply_" + self.suffix,
            "reason": "Aggregate peer usage payload capacity",
        }
        self.settings.core_usage.max_peer_usage_bytes = 1
        denied = await self.client.post(
            peer_path + "/commands", headers=self.headers, json=request
        )
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertIn("runtime_usage_peer_payload_capacity", denied.text)
        unchanged = (await self.get(peer_path))["data"]
        self.assertEqual(unchanged["revision"], peer_state["revision"])
        self.settings.core_usage.max_peer_usage_bytes = 1000000
        accepted = await self.client.post(
            peer_path + "/commands", headers=self.headers, json=request
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
