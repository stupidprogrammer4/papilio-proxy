import asyncio
import json
import os
import socket
import tempfile
from pathlib import Path

import uvicorn

from tests.real_core_runtime import RealCoreRuntime
from tests.test_fulfillment_workflow import FulfillmentWorkflowFixture
from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowTest,
)


class RuntimeAgentWorkflowTest(
    StaffAdministrationWorkflowTest, FulfillmentWorkflowFixture
):
    async def runtime_target(self, runtime, kind):
        capacity = self.settings.core_runtime
        assert capacity is not None
        capacity.enabled = True
        capacity.allow_start = True
        self.raw["core_runtime"]["enabled"] = True
        self.raw["core_runtime"]["allow_start"] = True
        _, subscription = await self.paid_subscription()
        port = runtime.port()
        node = await self.post(
            "/v1/admin/network/nodes",
            {
                "code": "runtime_" + kind + self.suffix,
                "label": "Owned runtime node",
                "public_host": "127.0.0.1",
                "public_port": port,
                "protocol": "vless_reality",
            },
        )
        enabled = await self.client.patch(
            f"/v1/admin/network/nodes/{node['node']['id']}/enabled",
            headers=self.headers,
            json={"enabled": True},
        )
        self.assertEqual(enabled.status_code, 200)
        core = await self.post(
            f"/v1/admin/network/nodes/{node['node']['id']}/cores",
            {
                "code": "owned_runtime",
                "label": "Owned runtime core",
                "kind": kind,
            },
        )
        configuration = await self.post(
            "/v1/admin/network/configurations",
            {
                "node_id": node["node"]["id"],
                "core_id": core["id"],
                "listen_port": port,
                "label": "Owned runtime inbound",
                "options": {
                    "protocol": "vless_reality",
                    "listen_address": "127.0.0.1",
                    "server_name": "localhost",
                    "target_port": runtime.handshake_port,
                },
            },
        )
        profile = await self.post(
            f"/v1/admin/network/configurations/{configuration['id']}/profiles",
            {"subscription_id": subscription["id"]},
        )
        client = await self.post(
            f"/v1/admin/network/configurations/profiles/{profile['id']}/client-download"
        )
        return node, core, configuration, client["content"]

    async def test_native_go_xray_control_and_recovery(
        self,
    ):
        await self.exercise_agent("xray")

    async def test_native_go_sing_box_control_and_recovery(
        self,
    ):
        await self.exercise_agent("sing_box")

    async def test_native_scheduler_worker_recovers_expired_runtime_lease(
        self,
    ):
        from datetime import UTC, datetime, timedelta

        from papilio.infra.db.transaction import transaction
        from sqlalchemy import update
        from sqlmodel import col

        from src.modules.network.core_runtime.infra.tables import (
            CoreRuntimeCommandTable,
        )
        from tests.scheduler_runtime import exercise_native_core_runtime

        capacity = self.settings.core_runtime
        assert capacity is not None
        capacity.enabled = True
        capacity.allow_start = True
        self.raw["core_runtime"]["enabled"] = True
        self.raw["core_runtime"]["allow_start"] = True
        _, request, nodes, _ = await self.setup_sale(
            protocols=("vless_reality",)
        )
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        configuration = (await self.get("/v1/admin/network/configurations"))[
            "data"
        ][0]
        base = f"/v1/admin/network/cores/{configuration['core_id']}/runtime"
        state = (await self.get(base))["data"]
        revision = await self.post(
            base + "/revisions",
            {"expected_revision": state["revision"], "mode": "merged"},
        )
        state = (await self.get(base))["data"]
        command = await self.post(
            base + "/commands",
            {
                "expected_revision": state["revision"],
                "action": "validate",
                "revision_id": revision["id"],
                "request_key": "recover_" + self.suffix,
                "reason": "Native lease recovery",
            },
        )
        node = nodes[0]
        claim = await self.client.post(
            f"/v1/nodes/{node['node']['code']}/runtime-commands/{command['id']}/claim",
            headers={"X-Papilio-Node-Key": node["agent_key"]},
        )
        self.assertEqual(claim.status_code, 200)
        async with self.connection.uow() as unit:
            async with transaction():
                await unit.execute(
                    update(CoreRuntimeCommandTable)
                    .where(col(CoreRuntimeCommandTable.id) == command["id"])
                    .values(
                        claim_until=datetime.now(UTC).replace(tzinfo=None)
                        - timedelta(seconds=1)
                    )
                )
        recovered = await asyncio.to_thread(
            exercise_native_core_runtime, self.raw, command["id"]
        )
        self.assertEqual(recovered, ("queued", 1))
        fresh = (await self.get(base + "/commands"))["data"]
        observed = next(row for row in fresh if row["id"] == command["id"])
        self.assertEqual(observed["state"], "queued")
        self.assertIsNone(observed["claim_until"])
        self.assertEqual(
            (await self.get(base))["data"]["observed_status"], "unknown"
        )

    async def exercise_agent(self, kind):
        binary = os.environ.get("PAPILIO_RUNTIME_TEST_BINARY")
        binaries = os.environ.get("PAPILIO_CORE_BIN_DIR")
        if not binary or not binaries:
            self.skipTest(
                "Explicit runtime binary and real-core opt-in required"
            )
        with tempfile.TemporaryDirectory(
            prefix="papilio-runtime-native-"
        ) as directory:
            runtime = await asyncio.to_thread(
                RealCoreRuntime(Path(directory), Path(binaries), 15).__enter__
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
                node, core, configuration, client = await self.runtime_target(
                    runtime, kind
                )
                cookie = self.client.cookies.get("papilio_admin")
                self.assertIsNotNone(cookie)
                assert cookie is not None
                admin_headers = {
                    **self.headers,
                    "Cookie": "papilio_admin=" + cookie,
                }
                result = await asyncio.to_thread(
                    exercise_runtime_agent,
                    Path(directory),
                    Path(binary),
                    Path(binaries),
                    f"http://127.0.0.1:{listener.getsockname()[1]}",
                    admin_headers,
                    node,
                    core,
                    configuration,
                    runtime,
                    client,
                )
                self.assertEqual(result, ("running", "running", "stopped"))
                state = (
                    await self.get(
                        f"/v1/admin/network/cores/{core['id']}/runtime"
                    )
                )["data"]
                self.assertEqual(state["observed_status"], "stopped")
            finally:
                server.should_exit = True
                await serving
                listener.close()
                await asyncio.to_thread(runtime.__exit__, None, None, None)


def exercise_runtime_agent(
    directory,
    binary,
    binaries,
    base_url,
    admin_headers,
    node,
    core,
    configuration,
    runtime,
    client_uri,
):
    import signal
    import subprocess
    import time

    import httpx

    config = {
        "enabled": True,
        "api_url": base_url,
        "node_code": node["node"]["code"],
        "state_directory": str(directory / "journal"),
        "binaries": {
            "xray": str(binaries / "xray"),
            "sing_box": str(binaries / "sing-box"),
        },
        "poll_interval_ms": 50,
        "http_timeout_ms": 5000,
        "max_response_bytes": 2097152,
        "max_idle_connections": 4,
        "page_size": 16,
        "max_pages_per_poll": 4,
        "max_artifacts": 16,
        "max_artifact_bytes": 1048576,
        "max_bundle_bytes": 2097152,
        "max_journal_bytes": 1048576,
        "max_receipts": 32,
        "max_cores": 4,
        "validation_timeout_ms": 5000,
        "startup_grace_ms": 150,
        "stop_timeout_ms": 2000,
        "max_processes": 4,
    }
    path = directory / "agent.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    log_path = directory / "agent.log"
    base = f"/v1/admin/network/cores/{core['id']}/runtime"
    with (
        httpx.Client(
            base_url=base_url,
            headers=admin_headers,
            timeout=10,
            trust_env=False,
        ) as api,
        log_path.open("w+") as log,
    ):
        log_path.chmod(0o600)

        def read_state():
            response = api.get(base)
            assert response.status_code == 200, "Runtime state read failed"
            return response.json()["data"]

        def snapshot():
            response = api.post(
                base + "/revisions",
                json={
                    "expected_revision": read_state()["revision"],
                    "mode": "merged",
                },
            )
            assert response.status_code == 200, "Runtime snapshot failed"
            return response.json()["data"]

        def command(action, revision_id=None, reconcile_mode=None):
            body = {
                "expected_revision": read_state()["revision"],
                "action": action,
                "revision_id": revision_id,
                "reconcile_mode": reconcile_mode,
                "request_key": "native_"
                + action
                + "_"
                + str(time.monotonic_ns()),
                "reason": "Owned runtime acceptance",
            }
            response = api.post(base + "/commands", json=body)
            assert response.status_code == 200, (
                f"Runtime {action} enqueue failed"
            )
            row = response.json()["data"]
            replay = api.post(base + "/commands", json=body)
            assert (
                replay.status_code == 200
                and replay.json()["data"]["id"] == row["id"]
            ), "Command replay duplicated work"
            return row

        def completed(row, outcome):
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                assert process.poll() is None, "Owned runtime agent exited"
                response = api.get(base + "/commands", params={"per_page": 16})
                assert response.status_code == 200
                selected = next(
                    item
                    for item in response.json()["data"]
                    if item["id"] == row["id"]
                )
                if selected["state"] in {"succeeded", "failed"}:
                    assert selected["state"] == outcome, (
                        f"Unexpected command result: {selected['state']} / "
                        f"{selected.get('error_code')}"
                    )
                    return selected
                time.sleep(0.05)
            raise AssertionError(
                "Runtime command did not finish within its acceptance deadline"
            )

        def port_closed():
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with socket.socket() as probe:
                    probe.settimeout(0.2)
                    if (
                        probe.connect_ex(
                            ("127.0.0.1", configuration["listen_port"])
                        )
                        != 0
                    ):
                        return
                time.sleep(0.05)
            raise AssertionError(
                "Owned core remained reachable after agent death"
            )

        revision = snapshot()
        env = {**os.environ, "PAPILIO_NODE_KEY": node["agent_key"]}
        process = subprocess.Popen(
            [str(binary), "-config", str(path)],
            env=env,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        try:
            completed(command("validate", revision["id"]), "succeeded")
            assert read_state()["validated_revision_id"] == revision["id"]
            completed(command("apply", revision["id"]), "succeeded")
            applied = read_state()
            assert (
                applied["applied_revision_id"] == revision["id"]
                and applied["observed_status"] == "running"
            )
            outbound = runtime.client(client_uri)
            runtime.exercise("installed-valid", outbound, accepted=True)
            outbound["uuid"] = "00000000-0000-0000-0000-000000000000"
            runtime.exercise("installed-invalid", outbound, accepted=False)
            modified = api.put(
                f"/v1/admin/network/configurations/{configuration['id']}/server-json",
                json={
                    "expected_revision": configuration["revision"],
                    "reason": "Controlled invalid core configuration",
                    "document": {
                        "mode": "managed",
                        "source": json.dumps(
                            {
                                "inbounds": [{"$papilio": "managed"}],
                                "outbounds": [
                                    {
                                        "tag": "broken",
                                        "type": "unsupported",
                                        "protocol": "unsupported",
                                    }
                                ],
                            }
                        ),
                    },
                },
            )
            assert modified.status_code == 200
            broken_revision = snapshot()
            completed(command("apply", broken_revision["id"]), "failed")
            assert read_state()["applied_revision_id"] == revision["id"]
            runtime.exercise(
                "preserved-after-failed-apply",
                runtime.client(client_uri),
                accepted=True,
            )
            completed(command("rollback", revision["id"]), "succeeded")
            rollback_status = read_state()["observed_status"]
            completed(command("restart"), "succeeded")
            restarted_status = read_state()["observed_status"]
            runtime.exercise(
                "restarted-valid", runtime.client(client_uri), accepted=True
            )
            os.kill(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
            port_closed()
            process = subprocess.Popen(
                [str(binary), "-config", str(path)],
                env=env,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
            completed(
                command("reconcile", reconcile_mode="observe"), "succeeded"
            )
            assert read_state()["observed_status"] == "stopped"
            port_closed()
            completed(command("restart"), "succeeded")
            runtime.exercise(
                "reauthorized-after-crash",
                runtime.client(client_uri),
                accepted=True,
            )
            completed(command("stop"), "succeeded")
            completed(
                command("reconcile", reconcile_mode="observe"), "succeeded"
            )
            assert read_state()["observed_status"] == "stopped"
            restored = api.put(
                f"/v1/admin/network/configurations/{configuration['id']}/server-json",
                json={
                    "expected_revision": modified.json()["data"]["revision"],
                    "reason": "Restore valid saved document",
                    "document": None,
                },
            )
            assert restored.status_code == 200
            fresh_revision = snapshot()
            completed(
                command("reconcile", fresh_revision["id"], "restore"),
                "succeeded",
            )
            runtime.exercise(
                "reconciled-valid", runtime.client(client_uri), accepted=True
            )
            completed(command("stop"), "succeeded")
            final = read_state()
            assert final["observed_status"] == "stopped"
            return rollback_status, restarted_status, final["observed_status"]
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
