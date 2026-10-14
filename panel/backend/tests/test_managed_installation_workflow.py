"""Native installation API with explicit constructed reporter fixtures."""

import asyncio
import hashlib
import json
import os
import socket
import tempfile
from contextvars import Context
from datetime import UTC, datetime
from pathlib import Path

import httpx
import uvicorn
from papilio.infra.db.transaction import transaction
from sqlalchemy import text

from src.modules.network.core_runtime.domain.memberships import (
    CoreProvisioningCapacity,
)
from src.modules.network.managed_runtime.domain.contracts import (
    ManagedRuntimeCapacity,
)
from src.modules.network.managed_runtime.domain.installations import (
    ManagedAdapterPolicy,
)
from tests.lock_observation import MySQLLockObservation
from tests.real_core_runtime import RealCoreRuntime
from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowFixture,
)


class ManagedInstallationWorkflowFixture(StaffAdministrationWorkflowFixture):
    async def setup_installation(self, materials=None, port=443):
        runtime = self.settings.core_runtime
        usage = self.settings.core_usage
        assert runtime is not None and usage is not None
        runtime.enabled = True
        runtime.allow_start = True
        usage.mode = "disabled"
        self.settings.core_provisioning = CoreProvisioningCapacity(
            mode="installed_only",
            batch_size=8,
            scan_cron="* * * * *",
            max_memberships=16,
            observation_seconds=60,
        )
        self.settings.managed_adapter = ManagedAdapterPolicy(
            enabled=True,
            source_commit="d2758a023cd7f4174a5a5fa4ff66e487d4342ba0",
            executable_sha256="a" * 64,
            materials_sha256="b" * 64,
            enforcement_sha256="c" * 64,
            window_policy_sha256="d" * 64,
            claim_seconds=60,
            observation_seconds=60,
            clock_skew_seconds=1,
            capacity=ManagedRuntimeCapacity.model_validate(
                {
                    "max_manifest_bytes": 1048576,
                    "max_window_bytes": 8192,
                    "max_snapshot_bytes": 65536,
                    "max_profiles_per_barrier": 16,
                    "max_windows_per_barrier": 16,
                    "max_pending_epochs": 8,
                    "max_retained_receipts": 32,
                    "max_validity_ms": 120000,
                    "operation_timeout_ms": 5000,
                    "scan_batch_size": 8,
                    "retry_seconds": 1,
                    "max_attempts": 3,
                }
            ),
        )
        customer, subscription = await self.paid_subscription()
        node = await self.post(
            "/v1/admin/network/nodes",
            {
                "code": "closed_" + self.suffix,
                "label": "Owned CLOSED API fixture",
                "public_host": "127.0.0.1",
                "public_port": port,
                "protocol": "vless_tls",
            },
        )
        enabled = await self.client.patch(
            f"/v1/admin/network/nodes/{node['node']['id']}/enabled",
            headers=self.headers,
            json={"enabled": True},
        )
        self.assertEqual(enabled.status_code, 200)
        configuration = await self.post(
            "/v1/admin/network/configurations",
            {
                "node_id": node["node"]["id"],
                "label": "CLOSED fixture",
                "listen_port": port,
                "options": {
                    "protocol": "vless_tls",
                    "listen_address": "127.0.0.1",
                    "server_name": "localhost",
                    "certificate_path": str(materials / "cert.pem")
                    if materials
                    else "/private/fixture/cert.pem",
                    "private_key_path": str(materials / "key.pem")
                    if materials
                    else "/private/fixture/key.pem",
                    "transport": "tcp",
                },
            },
        )
        if materials:
            edited = await self.client.put(
                f"/v1/admin/network/configurations/{configuration['id']}"
                "/server-json",
                headers=self.headers,
                json={
                    "expected_revision": configuration["revision"],
                    "reason": "Owned strict CLOSED log policy",
                    "document": {
                        "mode": "managed",
                        "source": json.dumps(
                            {
                                "inbounds": [{"$papilio": "managed"}],
                                "log": {"loglevel": "none"},
                            }
                        ),
                    },
                },
            )
            self.assertEqual(edited.status_code, 200, edited.text)
            configuration = edited.json()["data"]
        await self.post(
            f"/v1/admin/network/configurations/{configuration['id']}/profiles",
            {"subscription_id": subscription["id"]},
        )
        if getattr(self, "add_second_managed_profile", False):
            previous_suffix = self.suffix
            self.suffix = previous_suffix + "_second"
            try:
                _, second_subscription = await self.paid_subscription()
            finally:
                self.suffix = previous_suffix
            await self.post(
                f"/v1/admin/network/configurations/{configuration['id']}"
                "/profiles",
                {"subscription_id": second_subscription["id"]},
            )
            async with self.connection.uow() as unit:
                async with transaction(unit):
                    await unit.execute(
                        text(
                            "UPDATE tbl_subscriptions SET status='active',"
                            "provisioning_managed=0 WHERE id=:id"
                        ),
                        {"id": second_subscription["id"]},
                    )
        if getattr(self, "paid_managed_fixture", False):
            async with self.connection.uow() as fresh:
                requests = await fresh.execute(
                    text(
                        "SELECT id FROM tbl_provision_requests WHERE "
                        "subscription_id=:id"
                    ),
                    {"id": subscription["id"]},
                )
                request_id = requests.scalar_one()
            await self.post(f"/v1/admin/provisioning/{request_id}/prepare")
        else:
            async with self.connection.uow() as unit:
                async with transaction(unit):
                    await unit.execute(
                        text(
                            "UPDATE tbl_subscriptions SET status='active',"
                            "provisioning_managed=0 WHERE id=:id"
                        ),
                        {"id": subscription["id"]},
                    )
        runtime = f"/v1/admin/network/cores/{configuration['core_id']}/runtime"
        state = (await self.get(runtime))["data"]
        revision = await self.post(
            runtime + "/revisions",
            {"expected_revision": state["revision"], "mode": "merged"},
        )
        current = (await self.get(runtime))["data"]
        self.install_path = (
            f"/v1/admin/network/cores/{configuration['core_id']}"
            "/managed-installations"
        )
        self.issue_data = {
            "runtime_revision_id": revision["id"],
            "expected_runtime_revision": current["revision"],
        }
        self.node_path = (
            f"/v1/nodes/{node['node']['code']}/managed-installations"
        )
        self.node_headers = {"X-Papilio-Node-Key": node["agent_key"]}
        return customer, subscription, node, configuration

    async def observe_wait(self, table):
        database = self.settings.db
        assert database is not None
        return_value = await asyncio.to_thread(
            MySQLLockObservation().wait_for_queries,
            database.dsn,
            table,
            ("SELECT",),
            1,
            5.0,
            0.01,
            False,
        )
        return return_value

    async def issue(self):
        return_value = await self.client.post(
            self.install_path, headers=self.headers, json=self.issue_data
        )
        return return_value


class ManagedInstallationWorkflowTest(ManagedInstallationWorkflowFixture):
    async def test_new_assignment_during_node_wait_rejects_changed_scope(self):
        _, _, node, configuration = await self.setup_installation()
        old_suffix = self.suffix
        self.suffix = old_suffix + "_other"
        try:
            _, other = await self.paid_subscription()
        finally:
            self.suffix = old_suffix
        issue = None
        try:
            async with self.connection.uow() as holder:
                async with transaction(holder):
                    await holder.execute(
                        text(
                            (
                                "SELECT id FROM tbl_nodes WHERE id=:id FOR "
                                "UPDATE"
                            )
                        ),
                        {"id": node["node"]["id"]},
                    )
                    issue = asyncio.create_task(
                        self.issue(), context=Context()
                    )
                    self.assertTrue(await self.observe_wait("tbl_nodes"))
                    assigned_task = asyncio.create_task(
                        self.client.post(
                            f"/v1/admin/network/configurations/{configuration['id']}/profiles",
                            headers=self.headers,
                            json={"subscription_id": other["id"]},
                        ),
                        context=Context(),
                    )
                    assigned = await assigned_task
                    self.assertEqual(assigned.status_code, 200, assigned.text)
            response = await asyncio.wait_for(issue, 12)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(
                response.json()["error"]["message_code"],
                "managed_installation_scope_changed",
            )
        finally:
            if issue is not None and not issue.done():
                issue.cancel()
                await asyncio.gather(issue, return_exceptions=True)
        async with self.connection.uow() as fresh:
            rows = await fresh.execute(
                text(("SELECT COUNT(*) FROM tbl_managed_installations"))
            )
            self.assertEqual(rows.scalar_one(), 0)
            profiles = await fresh.execute(
                text(
                    (
                        "SELECT COUNT(*) FROM tbl_profiles WHERE "
                        "configuration_id=:id"
                    )
                ),
                {"id": configuration["id"]},
            )
            self.assertEqual(profiles.scalar_one(), 2)

    async def test_owner_change_during_node_wait_rejects_unknown_customer(
        self,
    ):
        _, subscription, node, _ = await self.setup_installation()
        other = await self.post(
            "/v1/admin/customers", {"display_name": "Changed scope owner"}
        )
        issue = None
        try:
            async with self.connection.uow() as holder:
                async with transaction(holder):
                    await holder.execute(
                        text(
                            (
                                "SELECT id FROM tbl_nodes WHERE id=:id FOR "
                                "UPDATE"
                            )
                        ),
                        {"id": node["node"]["id"]},
                    )
                    issue = asyncio.create_task(
                        self.issue(), context=Context()
                    )
                    self.assertTrue(await self.observe_wait("tbl_nodes"))
                    await holder.execute(
                        text(
                            (
                                "UPDATE tbl_subscriptions SET "
                                "customer_id=:owner WHERE id=:id"
                            )
                        ),
                        {"owner": other["id"], "id": subscription["id"]},
                    )
            response = await asyncio.wait_for(issue, 12)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(
                response.json()["error"]["message_code"],
                "managed_installation_scope_changed",
            )
        finally:
            if issue is not None and not issue.done():
                issue.cancel()
                await asyncio.gather(issue, return_exceptions=True)
        async with self.connection.uow() as fresh:
            rows = await fresh.execute(
                text(("SELECT COUNT(*) FROM tbl_managed_installations"))
            )
            self.assertEqual(rows.scalar_one(), 0)

    async def test_actual_go_agent_claims_closed_child_and_native_acknowledges(
        self,
    ):
        runtime_binary = os.environ.get("PAPILIO_RUNTIME_TEST_BINARY")
        managed_binary = os.environ.get("PAPILIO_MANAGED_TEST_BINARY")
        binaries = os.environ.get("PAPILIO_CORE_BIN_DIR")
        if not runtime_binary or not managed_binary or not binaries:
            self.skipTest(
                "Explicit owned fresh managed/runtime binaries required"
            )
        assert runtime_binary and managed_binary and binaries
        with tempfile.TemporaryDirectory(
            prefix="papilio-native-closed-install-"
        ) as name:
            root = Path(name)
            root.chmod(0o700)
            runtime = await asyncio.to_thread(
                RealCoreRuntime(root / "targets", Path(binaries), 15).__enter__
            )
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            server = uvicorn.Server(
                uvicorn.Config(
                    self.app,
                    lifespan="off",
                    access_log=False,
                    log_level="error",
                )
            )
            serving = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                inputs = root / "inputs"
                inputs.mkdir(mode=0o700)
                (inputs / "cert.pem").write_bytes(
                    runtime.certificate.read_bytes()
                )
                (inputs / "key.pem").write_bytes(runtime.key.read_bytes())
                (inputs / "cert.pem").chmod(0o600)
                (inputs / "key.pem").chmod(0o600)
                _, _, node, configuration = await self.setup_installation(
                    inputs, runtime.port()
                )
                from tests.managed_installation_agent import (
                    actual_registry,
                    run_native_closed_installation,
                )

                registry = await asyncio.to_thread(
                    actual_registry, root, inputs, Path(managed_binary)
                )
                policy = self.settings.managed_adapter
                assert policy is not None
                self.settings.managed_adapter = policy.model_copy(
                    update=registry["trusted_api_policy"]
                )
                issued = await self.issue()
                self.assertEqual(issued.status_code, 200, issued.text)
                id = issued.json()["data"]["id"]
                result = await asyncio.to_thread(
                    run_native_closed_installation,
                    root,
                    Path(runtime_binary),
                    registry["registry"],
                    id,
                    f"http://127.0.0.1:{listener.getsockname()[1]}",
                    node,
                )
                self.assertTrue(all(result.values()))
                async with self.connection.uow() as fresh:
                    records = await fresh.execute(
                        text(
                            "SELECT i.state,e.receipt_sha256,"
                            "e.encrypted_receipt "
                            "FROM tbl_managed_installations i "
                            "JOIN tbl_managed_epoches e "
                            "ON e.installation_id=i.id WHERE i.id=:id"
                        ),
                        {"id": id},
                    )
                    record = records.one()
                    self.assertEqual(record.state, "installed_closed")
                    self.assertEqual(len(record.receipt_sha256), 64)
                    self.assertNotIn(
                        "isolated_closed_startup_observation",
                        record.encrypted_receipt,
                    )
                    state = await fresh.execute(
                        text(
                            "SELECT applied_revision_id,observed_status "
                            "FROM tbl_core_runtime_states WHERE core_id=:id"
                        ),
                        {"id": configuration["core_id"]},
                    )
                    self.assertEqual(tuple(state.one()), (None, "unknown"))
            finally:
                server.should_exit = True
                await serving
                listener.close()
                await asyncio.to_thread(runtime.__exit__, None, None, None)

    async def test_installation_and_ip_admission_have_no_customer_node_cycle(
        self,
    ):
        customer, subscription, node, _ = await self.setup_installation()
        tasks = []
        try:
            async with self.connection.uow() as holder:
                async with transaction(holder):
                    await holder.execute(
                        text(
                            "SELECT id FROM tbl_nodes WHERE id=:id FOR UPDATE"
                        ),
                        {"id": node["node"]["id"]},
                    )
                    issue = asyncio.create_task(
                        self.issue(), context=Context()
                    )
                    tasks.append(issue)
                    self.assertTrue(await self.observe_wait("tbl_nodes"))
                    admission = asyncio.create_task(
                        self.client.post(
                            f"/v1/nodes/{node['node']['code']}/ip-admission",
                            headers=self.node_headers,
                            json={
                                "subscription_id": subscription["id"],
                                "source_ip": "192.0.2.222",
                            },
                        ),
                        context=Context(),
                    )
                    tasks.append(admission)
                    node_wait, customer_wait = await asyncio.gather(
                        self.observe_wait("tbl_nodes"),
                        self.observe_wait("tbl_customers"),
                    )
                    self.assertTrue(node_wait or customer_wait)
            outcomes = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), 12
            )
            self.assertFalse(
                [
                    value
                    for value in outcomes
                    if isinstance(value, BaseException)
                ],
                "Native installation and admission must not deadlock",
            )
            assert isinstance(outcomes[0], httpx.Response)
            assert isinstance(outcomes[1], httpx.Response)
            self.assertEqual(outcomes[0].status_code, 200)
            self.assertEqual(outcomes[1].status_code, 200)
            self.assertTrue(outcomes[1].json()["data"]["allowed"])
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        async with self.connection.uow() as fresh:
            row = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_managed_installations "
                    "WHERE core_id=:id"
                ),
                {"id": outcomes[0].json()["data"]["core_id"]},
            )
            self.assertEqual(row.scalar_one(), 1)
            epochs = await fresh.execute(
                text("SELECT COUNT(*) FROM tbl_managed_epoches")
            )
            self.assertEqual(epochs.scalar_one(), 0)

    async def test_closed_receipt_replay_keeps_activation_unavailable(
        self,
    ):
        _, _, _, configuration = await self.setup_installation()
        stale = await self.client.post(
            self.install_path,
            headers=self.headers,
            json={
                **self.issue_data,
                "expected_runtime_revision": self.issue_data[
                    "expected_runtime_revision"
                ]
                + 1,
            },
        )
        self.assertEqual(stale.status_code, 409)
        issues = await asyncio.gather(self.issue(), self.issue())
        self.assertEqual([row.status_code for row in issues], [200, 200])
        self.assertEqual(
            issues[0].json()["data"]["id"], issues[1].json()["data"]["id"]
        )
        id = issues[0].json()["data"]["id"]
        claimed = await self.client.post(
            f"{self.node_path}/{id}/claim", headers=self.node_headers
        )
        self.assertEqual(claimed.status_code, 200, claimed.text)
        claim = claimed.json()["data"]
        expected = claim["expectation"]
        document = {
            "state": "isolated_closed_startup_observation",
            "epoch": "e" * 32,
            "installation": expected["installation"],
            "adapter_revision": expected["adapter_revision"],
            "source_commit": expected["source_commit"],
            "module": "github.com/xtls/xray-core@v1.260327.0",
            "accounting_scope": "decoded_managed_tcp_payload_admission",
            "accounting_mode": "window_component",
            "enforcement_mode": "strict_decoded",
            "enforcement_sha256": expected["enforcement_sha256"],
            "window_policy_sha256": expected["window_policy_sha256"],
            "profiles": expected["profiles"],
            "api_authority": False,
            "budget_enforced": False,
            "deadline_enforced": False,
            "historical_only": True,
            "observed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        }
        original = json.dumps(document, separators=(",", ":"))
        body = {
            "claim_token": claim["claim_token"],
            "original_receipt": original,
            "receipt": {
                "epoch": "e" * 32,
                "receipt_sha256": hashlib.sha256(
                    original.encode()
                ).hexdigest(),
                "bytes": len(original.encode()),
            },
        }
        path = f"{self.node_path}/{id}/acknowledge"
        unknown = await self.client.post(
            f"{self.node_path}/{id + 1}/acknowledge",
            headers=self.node_headers,
            json=body,
        )
        self.assertEqual(unknown.status_code, 404)
        changed_document = {
            **document,
            "installation": {
                **document["installation"],
                "executable_sha256": "0" * 64,
            },
        }
        changed_original = json.dumps(changed_document, separators=(",", ":"))
        changed_build = {
            **body,
            "original_receipt": changed_original,
            "receipt": {
                "epoch": "e" * 32,
                "receipt_sha256": hashlib.sha256(
                    changed_original.encode()
                ).hexdigest(),
                "bytes": len(changed_original.encode()),
            },
        }
        rejected_build = await self.client.post(
            path, headers=self.node_headers, json=changed_build
        )
        self.assertEqual(rejected_build.status_code, 409)
        outcomes = await asyncio.gather(
            self.client.post(path, headers=self.node_headers, json=body),
            self.client.post(path, headers=self.node_headers, json=body),
        )
        self.assertEqual([row.status_code for row in outcomes], [200, 200])
        self.assertEqual(
            outcomes[0].json()["data"], outcomes[1].json()["data"]
        )
        self.assertFalse(outcomes[0].json()["data"]["admission_available"])
        policy = self.settings.managed_adapter
        assert policy is not None
        self.settings.managed_adapter = policy.model_copy(
            update={"enabled": False}
        )
        replay = await self.client.post(
            path, headers=self.node_headers, json=body
        )
        self.assertEqual(replay.status_code, 200)
        changed = {**body, "original_receipt": original + " "}
        denied = await self.client.post(
            path, headers=self.node_headers, json=changed
        )
        self.assertEqual(denied.status_code, 409)
        async with self.connection.uow() as fresh:
            state = await fresh.execute(
                text(
                    "SELECT applied_revision_id,observed_status "
                    "FROM tbl_core_runtime_states WHERE core_id=:id"
                ),
                {"id": configuration["core_id"]},
            )
            self.assertEqual(tuple(state.one()), (None, "unknown"))
            epochs = await fresh.execute(
                text("SELECT COUNT(*) FROM tbl_managed_epoches")
            )
            self.assertEqual(epochs.scalar_one(), 1)
