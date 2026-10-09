import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from sqlalchemy import text

from src.modules.network.node_capabilities.domain.contracts import (
    NodeCapabilityCapacity,
)
from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowFixture,
)


def capability_submission(observed_at: datetime, report_id: str | None = None):
    def operation(implemented, scope, reason):
        return {
            "implemented": implemented,
            "compatibility": "unavailable",
            "scope": scope,
            "reason_code": reason,
        }

    adapters = []
    for kind in ("xray", "sing_box", "openvpn", "wireguard", "hysteria"):
        installed = kind in ("xray", "sing_box")
        reason = (
            "core_binary_unavailable" if installed else "adapter_unavailable"
        )
        adapters.append(
            {
                "kind": kind,
                "adapter_revision": 1,
                "executable": {
                    "available": False,
                    "version": None,
                    "sha256": None,
                    "v2ray_api_build_tag": False,
                    "reason_code": reason,
                },
                "validation": operation(
                    installed, "local_immutable_document_validation", reason
                ),
                "installation": operation(
                    installed,
                    "fresh_authorized_immutable_bundle_lifecycle",
                    reason,
                ),
                "installed_membership": operation(
                    installed, "live_exact_installed_membership_only", reason
                ),
                "counters": operation(
                    kind == "xray",
                    "merged_xray_scoped_cumulative_counters",
                    "counter_adapter_unavailable",
                ),
                "polled_stop": operation(
                    kind == "xray",
                    "whole_merged_core_stop_with_poll_overrun",
                    "counter_adapter_unavailable",
                ),
                "strict_quota_expiry": operation(
                    False,
                    "no_strict_quota_or_expiry_guarantee",
                    "strict_enforcement_unavailable",
                ),
                "ip_admission": operation(
                    False,
                    "source_ip_not_device_identity",
                    "runtime_ip_adapter_unavailable",
                ),
                "device_admission": operation(
                    False,
                    "no_device_count_guarantee",
                    "device_admission_unavailable",
                ),
                "final_counters": operation(
                    False,
                    "unresolved_grants_preserved",
                    "engine_completion_unavailable",
                ),
                "protocol_matrix": operation(
                    False,
                    "export_or_binary_version_is_not_protocol_acceptance",
                    "protocol_matrix_not_reported",
                ),
            }
        )
    report = {
        "schema_revision": 1,
        "observed_at": observed_at.astimezone(UTC).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        ),
        "adapters": adapters,
    }
    canonical = json.dumps(
        report, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()
    return {
        "report_id": report_id or uuid4().hex,
        "report_sha256": hashlib.sha256(canonical).hexdigest(),
        "report": report,
    }


class NodeCapabilityWorkflowTest(StaffAdministrationWorkflowFixture):
    def enable_capabilities(self, **changes):
        policy = {
            "enabled": True,
            "max_report_bytes": 16384,
            "max_history_per_node": 8,
            "page_size": 2,
            "max_page_size": 4,
            "freshness_seconds": 10,
            "max_report_age_seconds": 120,
            "future_skew_seconds": 5,
            **changes,
        }
        self.settings.node_capabilities = (
            NodeCapabilityCapacity.model_validate(policy)
        )
        self.raw["node_capabilities"] = policy

    async def enrolled_node(self, suffix="a"):
        result = await self.post(
            "/v1/admin/network/nodes",
            {
                "code": "cap_" + self.suffix + suffix,
                "label": "Owned capability node",
                "public_host": "127.0.0.1",
                "public_port": 443,
                "protocol": "vless_reality",
            },
        )
        return result

    async def submit(self, node, body, key=None):
        result = await self.client.post(
            f"/v1/nodes/{node['node']['code']}/capability-observations",
            headers={"X-Papilio-Node-Key": key or node["agent_key"]},
            json=body,
        )
        return result

    async def test_native_receipts_history_replay_freshness_and_authorization(
        self,
    ):
        self.enable_capabilities(max_history_per_node=2)
        assert self.settings.node_capabilities is not None
        node, other = await asyncio.gather(
            self.enrolled_node(), self.enrolled_node("b")
        )
        base = f"/v1/admin/network/nodes/{node['node']['id']}/capabilities"
        absent = (await self.get(base + "/latest"))["data"]
        self.assertEqual(absent["status"], "absent")
        self.assertIsNone(absent["observation"])
        now = datetime.now(UTC)
        newer = capability_submission(now - timedelta(seconds=2))
        older = capability_submission(now - timedelta(seconds=4))
        accepted_new, accepted_old = await asyncio.gather(
            self.submit(node, newer), self.submit(node, older)
        )
        self.assertEqual(accepted_new.status_code, 200)
        self.assertEqual(accepted_old.status_code, 200)
        receipt = accepted_new.json()["data"]
        self.assertEqual(receipt["report_id"], newer["report_id"])
        self.assertEqual(receipt["node_code"], node["node"]["code"])
        self.assertEqual(receipt["report_sha256"], newer["report_sha256"])
        latest = (await self.get(base + "/latest"))["data"]
        self.assertEqual(latest["status"], "fresh")
        self.assertEqual(
            latest["observation"]["report_id"], newer["report_id"]
        )
        self.assertEqual(
            latest["observation"]["evidence_kind"],
            "authenticated_node_self_report",
        )
        self.assertFalse(
            latest["observation"]["report"]["adapters"][0]["final_counters"][
                "implemented"
            ]
        )
        pages = await asyncio.gather(
            self.get(base + "/history?page=1&per_page=1"),
            self.get(base + "/history?page=2&per_page=1"),
        )
        self.assertTrue(
            all(row["meta"]["pager"]["total_items"] == 2 for row in pages)
        )
        self.assertEqual(
            {row["data"][0]["report_id"] for row in pages},
            {newer["report_id"], older["report_id"]},
        )
        denied = await self.submit(other, newer, node["agent_key"])
        self.assertEqual(denied.status_code, 401)
        other_absent = (
            await self.get(
                f"/v1/admin/network/nodes/{other['node']['id']}/capabilities/latest"
            )
        )["data"]
        self.assertEqual(other_absent["status"], "absent")
        conflict = await self.submit(
            node, capability_submission(now, newer["report_id"])
        )
        self.assertEqual(conflict.status_code, 409)
        full = await self.submit(node, capability_submission(now))
        self.assertEqual(full.status_code, 409)
        self.assertIn("capability_history_capacity", full.text)
        self.settings.node_capabilities.freshness_seconds = 1
        self.assertEqual(
            (await self.get(base + "/latest"))["data"]["status"], "stale"
        )
        self.settings.node_capabilities.max_report_bytes = 1
        self.settings.node_capabilities.max_history_per_node = 1
        self.settings.node_capabilities.max_report_age_seconds = 1
        self.settings.node_capabilities.enabled = False
        replay = await self.submit(node, newer)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["data"], receipt)
        disabled = await self.submit(other, capability_submission(now))
        self.assertEqual(disabled.status_code, 409)
        self.assertIn("capability_observations_disabled", disabled.text)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="https://admin.example.com",
        ) as anonymous:
            denied_read = await anonymous.get(base + "/latest")
        self.assertIn(denied_read.status_code, (401, 403))
        staff = await self.post(
            "/v1/admin/staff",
            {
                "username": "cap_read_" + self.suffix,
                "password": "isolated-cap-reader",
                "is_active": True,
                "scopes": ["customers:read"],
            },
        )
        limited, _ = await self.login_staff(
            staff["username"], "isolated-cap-reader"
        )
        try:
            self.assertEqual(
                (await limited.get(base + "/history")).status_code, 403
            )
        finally:
            await limited.aclose()

    async def test_native_grammar_key_fault_and_no_runtime_effect(
        self,
    ):
        self.enable_capabilities()
        assert self.settings.node_capabilities is not None
        node = await self.enrolled_node()
        now = datetime.now(UTC)
        expired, future = await asyncio.gather(
            self.submit(
                node, capability_submission(now - timedelta(seconds=180))
            ),
            self.submit(
                node, capability_submission(now + timedelta(seconds=30))
            ),
        )
        self.assertEqual(expired.status_code, 409)
        self.assertEqual(future.status_code, 409)
        malformed = capability_submission(now)
        malformed["report_sha256"] = "a" * 64
        self.assertEqual((await self.submit(node, malformed)).status_code, 409)
        impossible = capability_submission(now)
        impossible["report"]["adapters"][0]["final_counters"][
            "implemented"
        ] = True
        self.assertEqual(
            (await self.submit(node, impossible)).status_code, 422
        )
        self.settings.node_capabilities.future_skew_seconds = 60
        body = capability_submission(now + timedelta(seconds=30))
        body["report"]["unknown_private_field"] = "not-persisted"
        accepted = await self.submit(node, body)
        self.assertEqual(accepted.status_code, 200)
        self.settings.node_capabilities.future_skew_seconds = 0
        latest = (
            await self.get(
                f"/v1/admin/network/nodes/{node['node']['id']}/capabilities/latest"
            )
        )["data"]
        self.assertEqual(latest["status"], "future")
        self.assertNotIn(
            "unknown_private_field", latest["observation"]["report"]
        )
        # Owned DB fault; no public key-rotation workflow exists.
        replacement = "owned-replacement-key-" + self.suffix
        async with self.connection.uow() as independent:
            await independent.execute(
                text(
                    "UPDATE tbl_nodes SET agent_key_hash=:digest "
                    "WHERE id=:node"
                ),
                {
                    "digest": hashlib.sha256(replacement.encode()).hexdigest(),
                    "node": node["node"]["id"],
                },
            )
            await independent.commit()
        invalidated = await self.submit(node, body)
        self.assertEqual(invalidated.status_code, 401)
        replay = await self.submit(node, body, replacement)
        self.assertEqual(replay.status_code, 200)
        async with self.connection.uow() as independent:
            rows = await independent.execute(
                text(
                    "SELECT (SELECT COUNT(*) FROM tbl_core_runtime_commands), "
                    "(SELECT COUNT(*) FROM tbl_core_runtime_states), "
                    "(SELECT COUNT(*) FROM tbl_provision_tasks), "
                    "(SELECT COUNT(*) FROM tbl_usage_grants)"
                )
            )
            self.assertEqual(tuple(rows.one()), (0, 0, 0, 0))

    async def test_native_unconfigured_preserves_node_routes(self):
        self.settings.node_capabilities = None
        node = await self.enrolled_node()
        reply = await self.submit(
            node, capability_submission(datetime.now(UTC))
        )
        self.assertEqual(reply.status_code, 409)
        self.assertIn("capability_observations_unconfigured", reply.text)
        nodes = await self.get("/v1/admin/network/nodes")
        self.assertTrue(nodes["success"])
        async with self.connection.uow() as unit:
            rows = await unit.execute(
                text("SELECT COUNT(*) FROM tbl_node_capability_observations")
            )
        self.assertEqual(rows.scalar_one(), 0)

    async def test_native_key_fault_during_observed_node_lock_wait(self):
        from contextvars import Context

        from papilio.infra.db.transaction import transaction

        from tests.lock_observation import MySQLLockObservation

        self.enable_capabilities()
        node = await self.enrolled_node()
        pending = None
        replacement = "owned-lockwait-key-" + self.suffix
        try:
            async with self.connection.uow() as unit:
                async with transaction(unit):
                    await unit.execute(
                        text(
                            "SELECT id FROM tbl_nodes WHERE id=:id FOR UPDATE"
                        ),
                        {"id": node["node"]["id"]},
                    )
                    pending = asyncio.create_task(
                        self.submit(
                            node, capability_submission(datetime.now(UTC))
                        ),
                        context=Context(),
                    )
                    assert self.settings.db is not None
                    blocked = await asyncio.to_thread(
                        MySQLLockObservation().wait_for_queries,
                        self.settings.db.dsn,
                        "tbl_nodes",
                        ("SELECT",),
                        1,
                        5,
                        0.02,
                        True,
                    )
                    self.assertTrue(blocked)
                    self.assertFalse(pending.done())
                    # Owned DB fault injection, not a public rotation feature.
                    await unit.execute(
                        text(
                            "UPDATE tbl_nodes SET agent_key_hash=:digest "
                            "WHERE id=:id"
                        ),
                        {
                            "digest": hashlib.sha256(
                                replacement.encode()
                            ).hexdigest(),
                            "id": node["node"]["id"],
                        },
                    )
            result = await asyncio.wait_for(pending, timeout=5)
            self.assertEqual(result.status_code, 401)
            async with self.connection.uow() as unit:
                rows = await unit.execute(
                    text(
                        "SELECT COUNT(*) FROM tbl_node_capability_observations"
                    )
                )
            self.assertEqual(rows.scalar_one(), 0)
        finally:
            if pending is not None and not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)

    async def test_actual_go_metadata_publication_native_receipt(self):
        import os
        import socket
        import tempfile
        from pathlib import Path

        import uvicorn

        from tests.node_capability_agent import publish_actual_capabilities

        binary = os.environ.get("PAPILIO_RUNTIME_TEST_BINARY")
        binaries = os.environ.get("PAPILIO_CORE_BIN_DIR")
        if not binary or not binaries:
            self.skipTest(
                "Explicit private Go/pinned executable opt-in required"
            )
        self.enable_capabilities()
        node = await self.enrolled_node()
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(
            uvicorn.Config(
                self.app, lifespan="off", access_log=False, log_level="error"
            )
        )
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            with tempfile.TemporaryDirectory(
                prefix="papilio-capability-native-"
            ) as private:
                directory = Path(private)
                directory.chmod(0o700)
                receipt = await asyncio.to_thread(
                    publish_actual_capabilities,
                    directory,
                    Path(binary),
                    Path(binaries),
                    f"http://127.0.0.1:{listener.getsockname()[1]}",
                    node,
                )
                latest = (
                    await self.get(
                        f"/v1/admin/network/nodes/{node['node']['id']}"
                        "/capabilities/latest"
                    )
                )["data"]
                observed = latest["observation"]
                self.assertEqual(latest["status"], "fresh")
                self.assertEqual(receipt["report_id"], observed["report_id"])
                self.assertEqual(
                    receipt["report_sha256"], observed["report_sha256"]
                )
                adapters = {
                    row["kind"]: row for row in observed["report"]["adapters"]
                }
                self.assertEqual(
                    adapters["xray"]["executable"]["version"], "26.3.27"
                )
                self.assertEqual(
                    adapters["sing_box"]["executable"]["version"], "1.12.25"
                )
                self.assertEqual(
                    adapters["xray"]["installation"]["compatibility"],
                    "reference_match",
                )
                self.assertFalse(
                    adapters["xray"]["final_counters"]["implemented"]
                )
                self.assertFalse(
                    adapters["sing_box"]["executable"]["v2ray_api_build_tag"]
                )
        finally:
            server.should_exit = True
            await asyncio.wait_for(serving, timeout=10)
            listener.close()

    async def test_populated_0050_upgrade_preserves_data_and_refuses_downgrade(
        self,
    ):
        import os
        from unittest.mock import patch

        from alembic import command
        from alembic.config import Config

        self.enable_capabilities()
        node = await self.enrolled_node()
        customer = await self.post(
            "/v1/admin/customers",
            {"display_name": "Owned migration customer"},
        )
        assert self.settings.db is not None
        migration = Config("alembic.ini")
        migration.set_main_option("sqlalchemy.url", self.settings.db.dsn)
        async with self.connection.uow() as unit:
            await unit.execute(
                text(
                    "INSERT INTO tbl_wallets(customer_id,balance_rial) "
                    "VALUES(:customer,125000)"
                ),
                {"customer": customer["id"]},
            )
            await unit.commit()
        with patch.dict(os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(
                command.downgrade, migration, "0050_checkout_attempt_fences"
            )
            await asyncio.to_thread(
                command.upgrade, migration, "0051_node_capabilities"
            )
        async with self.connection.uow() as unit:
            balance = await unit.execute(
                text(
                    "SELECT balance_rial FROM tbl_wallets "
                    "WHERE customer_id=:customer"
                ),
                {"customer": customer["id"]},
            )
            code = await unit.execute(
                text("SELECT code FROM tbl_nodes WHERE id=:node"),
                {"node": node["node"]["id"]},
            )
            self.assertEqual(balance.scalar_one(), 125000)
            self.assertEqual(code.scalar_one(), node["node"]["code"])
        submitted = await self.submit(
            node, capability_submission(datetime.now(UTC))
        )
        self.assertEqual(submitted.status_code, 200)
        with patch.dict(os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}):
            with self.assertRaisesRegex(RuntimeError, "replay receipts"):
                await asyncio.to_thread(
                    command.downgrade,
                    migration,
                    "0050_checkout_attempt_fences",
                )
        async with self.connection.uow() as unit:
            head = await unit.execute(
                text("SELECT version_num FROM alembic_version")
            )
            receipts = await unit.execute(
                text("SELECT COUNT(*) FROM tbl_node_capability_observations")
            )
            self.assertEqual(head.scalar_one(), "0051_node_capabilities")
            self.assertEqual(receipts.scalar_one(), 1)

    async def test_node_locked_concurrent_history_capacity(self):
        from contextvars import Context

        from papilio.infra.db.transaction import transaction

        from tests.lock_observation import MySQLLockObservation

        self.enable_capabilities(max_history_per_node=1)
        node = await self.enrolled_node()
        pending = []
        try:
            async with self.connection.uow() as unit:
                async with transaction(unit):
                    await unit.execute(
                        text(
                            "SELECT id FROM tbl_nodes WHERE id=:id FOR UPDATE"
                        ),
                        {"id": node["node"]["id"]},
                    )
                    first = capability_submission(datetime.now(UTC))
                    second = capability_submission(datetime.now(UTC))
                    pending = [
                        asyncio.create_task(
                            self.submit(node, first), context=Context()
                        ),
                        asyncio.create_task(
                            self.submit(node, second), context=Context()
                        ),
                    ]
                    assert self.settings.db is not None
                    blocked = await asyncio.to_thread(
                        MySQLLockObservation().wait_for_queries,
                        self.settings.db.dsn,
                        "tbl_nodes",
                        ("SELECT",),
                        2,
                        5,
                        0.02,
                        True,
                    )
                    self.assertTrue(blocked)
                    self.assertTrue(all(not task.done() for task in pending))
            replies = await asyncio.wait_for(
                asyncio.gather(*pending), timeout=5
            )
            self.assertEqual(
                sorted(row.status_code for row in replies), [200, 409]
            )
            async with self.connection.uow() as unit:
                count = await unit.execute(
                    text(
                        "SELECT COUNT(*) FROM tbl_node_capability_observations"
                    )
                )
            self.assertEqual(count.scalar_one(), 1)
        finally:
            active = [task for task in pending if not task.done()]
            for task in active:
                task.cancel()
            await asyncio.gather(*active, return_exceptions=True)

    async def test_concurrent_first_reports_and_exact_same_report_replay(self):
        self.enable_capabilities(max_history_per_node=1)
        first, second = await asyncio.gather(
            self.enrolled_node("a"), self.enrolled_node("b")
        )
        body = capability_submission(datetime.now(UTC))
        replies = await asyncio.gather(
            self.submit(first, body), self.submit(second, body)
        )
        self.assertEqual([row.status_code for row in replies], [200, 200])
        self.assertNotEqual(
            replies[0].json()["data"]["observation_id"],
            replies[1].json()["data"]["observation_id"],
        )
        third = await self.enrolled_node("c")
        same = await asyncio.gather(
            self.submit(third, body), self.submit(third, body)
        )
        self.assertEqual([row.status_code for row in same], [200, 200])
        self.assertEqual(same[0].json()["data"], same[1].json()["data"])
        original = replies[0].json()["data"]
        replays = await asyncio.gather(
            self.submit(first, body), self.submit(first, body)
        )
        self.assertTrue(all(row.status_code == 200 for row in replays))
        self.assertTrue(all(row.json()["data"] == original for row in replays))

    async def test_standalone_preserves_outer_work_and_pool_isolation(
        self,
    ):
        from papilio.errors.exceptions import ConflictException
        from papilio.infra.db.connection import DBConnection
        from papilio.infra.db.uow import MySQLUnitOfWork

        from src.modules.network.node_capabilities.app.commands import (
            NodeCapabilityCommand,
        )
        from src.modules.network.node_capabilities.app.services import (
            NodeCapabilityService,
        )
        from src.modules.network.node_capabilities.domain.contracts import (
            NodeCapabilityReceived,
        )
        from src.modules.network.node_capabilities.infra.mysql import (
            NodeCapabilityObservationRepository,
        )
        from src.modules.network.node_capabilities.infra.readers import (
            NodeCapabilityObservationReader,
        )
        from src.modules.network.nodes.app.services import NodeService
        from src.modules.network.nodes.infra.mysql import NodeRepository

        self.enable_capabilities()
        node = await self.enrolled_node()
        assert self.settings.db is not None
        assert self.settings.node_capabilities is not None
        owned = DBConnection(
            dsn=self.settings.db.dsn,
            pool_size=1,
            max_overflow=0,
            pool_timeout=5,
            pool_recycle=1800,
            uow_factory=MySQLUnitOfWork,
        )

        def command_for(unit: MySQLUnitOfWork):
            assert self.settings.node_capabilities is not None
            return NodeCapabilityCommand(
                NodeService(NodeRepository(unit), self.settings),
                NodeCapabilityService(
                    NodeCapabilityObservationRepository(unit)
                ),
                NodeCapabilityObservationReader(unit),
                self.settings.node_capabilities,
                unit,
            )

        body = NodeCapabilityReceived.model_validate(
            capability_submission(datetime.now(UTC))
        )
        try:
            async with owned.uow() as unit:
                original = (
                    await unit.execute(
                        text("SELECT CONNECTION_ID(), @@transaction_isolation")
                    )
                ).one()
            async with owned.uow() as unit:
                receipt = await command_for(unit).receive(
                    node["node"]["code"], node["agent_key"], body
                )
                self.assertEqual(receipt.report_id, body.report_id)
            async with owned.uow() as unit:
                restored = (
                    await unit.execute(
                        text("SELECT CONNECTION_ID(), @@transaction_isolation")
                    )
                ).one()
                self.assertEqual(tuple(restored), tuple(original))
                await unit.rollback()
                async with unit.transaction():
                    await unit.execute(
                        text("UPDATE tbl_nodes SET label=:label WHERE id=:id"),
                        {
                            "label": "Outer caller change",
                            "id": node["node"]["id"],
                        },
                    )
                    with self.assertRaises(ConflictException):
                        await command_for(unit).receive(
                            node["node"]["code"], node["agent_key"], body
                        )
                    self.assertTrue(unit.in_transaction)
            async with owned.uow() as unit:
                label = (
                    await unit.execute(
                        text("SELECT label FROM tbl_nodes WHERE id=:id"),
                        {"id": node["node"]["id"]},
                    )
                ).scalar_one()
                self.assertEqual(label, "Outer caller change")
                with self.assertRaises(ConflictException):
                    await command_for(unit).receive(
                        node["node"]["code"], node["agent_key"], body
                    )
                self.assertTrue(unit.in_transaction)
                await unit.commit()
        finally:
            await owned.dispose()
