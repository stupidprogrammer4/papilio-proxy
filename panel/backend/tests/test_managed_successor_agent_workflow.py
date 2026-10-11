"""Native paid activation, three actual TLS windows and durable finality."""

import asyncio
import json
import os
import socket
import tempfile
from pathlib import Path

import uvicorn
from sqlalchemy import text

from src.modules.network.managed_runtime.domain.successors import (
    ManagedSuccessorLimits,
    ManagedSuccessorPolicy,
)
from tests.managed_installation_agent import actual_registry, compact, digest
from tests.managed_successor_agent import run_native_successor_cycles
from tests.real_core_runtime import RealCoreRuntime
from tests.test_managed_installation_workflow import (
    ManagedInstallationWorkflowFixture,
)


class ManagedSuccessorAgentWorkflowTest(ManagedInstallationWorkflowFixture):
    paid_managed_fixture = True

    async def test_actual_paid_three_tls_windows_account_once_and_replay(self):
        runtime_binary = os.environ.get("PAPILIO_RUNTIME_TEST_BINARY")
        managed_binary = os.environ.get("PAPILIO_MANAGED_TEST_BINARY")
        binaries = os.environ.get("PAPILIO_CORE_BIN_DIR")
        if not runtime_binary or not managed_binary or not binaries:
            self.skipTest(
                "Explicit owned fresh agent/managed/stock binaries required"
            )
        assert runtime_binary and managed_binary and binaries
        self.settings.usage.policy.mode = "reserved"
        payloads = (
            b"paid-native-initial-window-proof",
            b"paid-native-first-successor-window-proof",
            b"paid-native-second-successor-cumulative-window-proof",
        )
        with tempfile.TemporaryDirectory(
            prefix="papilio-native-successors-"
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
                (
                    _,
                    subscription,
                    node,
                    configuration,
                ) = await self.setup_installation(inputs, runtime.port())
                registry = await asyncio.to_thread(
                    actual_registry, root, inputs, Path(managed_binary)
                )
                registry["registry"]["window_policy"].update(
                    {
                        "max_windows": 8,
                        "max_records": 16,
                        "max_admission_receipts": 8,
                    }
                )
                registry["registry"]["component_policy"]["max_barriers"] = 8
                registry["trusted_api_policy"][
                    "window_policy_sha256"
                ] = await asyncio.to_thread(
                    digest,
                    compact(
                        registry["registry"]["window_policy"], canonical=True
                    ),
                )
                policy = self.settings.managed_adapter
                assert policy is not None
                self.settings.managed_adapter = policy.model_copy(
                    update={
                        **registry["trusted_api_policy"],
                        "window_mode": "reserved",
                        "paid_mode": "strict_admission",
                        "successor_policy": ManagedSuccessorPolicy(
                            mode="bounded",
                            limits=ManagedSuccessorLimits(
                                max_windows_per_profile_epoch=4,
                                max_windows_per_epoch=8,
                                max_epoch_seconds=300,
                                max_requested_bytes=1024,
                            ),
                        ),
                    }
                )
                issued = await self.issue()
                self.assertEqual(issued.status_code, 200, issued.text)
                installation_id = issued.json()["data"]["id"]
                async with self.connection.uow() as fresh:
                    rows = await fresh.execute(
                        text(
                            "SELECT p.id,t.id,r.id,s.status,s.activated_at "
                            "FROM tbl_profiles p JOIN tbl_provision_tasks t "
                            "ON t.profile_id=p.id JOIN tbl_provision_reques"
                            "ts r "
                            "ON r.id=t.request_id JOIN tbl_subscriptions s "
                            "ON s.id=r.subscription_id WHERE "
                            "p.configuration_id=:configuration AND s.id=:su"
                            "bscription"
                        ),
                        {
                            "configuration": configuration["id"],
                            "subscription": subscription["id"],
                        },
                    )
                    profile_id, task_id, request_id, status, activated = tuple(
                        rows.one()
                    )
                    self.assertEqual(
                        (status, activated), ("pending_provision", None)
                    )
                result = await asyncio.to_thread(
                    run_native_successor_cycles,
                    root,
                    Path(runtime_binary),
                    registry["registry"],
                    installation_id,
                    profile_id,
                    f"http://127.0.0.1:{listener.getsockname()[1]}",
                    node,
                    Path(binaries),
                    task_id,
                    payloads,
                    freeze_after_ms=8000,
                )
                self.assertTrue(
                    result.replay_unchanged and result.child_stopped
                )
                entries = (result.initial, *result.successors)
                self.assertEqual(len(entries), 3)
                self.assertEqual(
                    len({e["issued"]["window"]["window_id"] for e in entries}),
                    3,
                )
                self.assertEqual(
                    len({e["issued"]["window"]["epoch"] for e in entries}), 1
                )
                async with self.connection.uow() as fresh:
                    grants = await fresh.execute(
                        text(
                            "SELECT w.window_id,w.grant_id,w.provision_task"
                            "_id,"
                            "w.baseline_upload_bytes,w.baseline_download_by"
                            "tes,"
                            "w.predecessor_id,w.encrypted_window,g.allocate"
                            "d_bytes,"
                            "g.upload_bytes,g.download_bytes,g.is_closed,g."
                            "sequence "
                            "FROM tbl_managed_windows w JOIN tbl_usage_gran"
                            "ts g "
                            "ON g.id=w.grant_id WHERE w.subscription_id=:id"
                            " ORDER BY w.id"
                        ),
                        {"id": subscription["id"]},
                    )
                    rows = tuple(grants.all())
                    self.assertEqual(len(rows), 3)
                    baseline = 0
                    for row, entry, payload in zip(
                        rows, entries, payloads, strict=True
                    ):
                        self.assertEqual(
                            tuple(row[:5]),
                            (
                                entry["issued"]["window"]["window_id"],
                                entry["issued"]["window"]["grant_id"],
                                task_id,
                                baseline,
                                baseline,
                            ),
                        )
                        self.assertEqual(
                            tuple(row[7:]),
                            (1024, len(payload), len(payload), 1, 1),
                        )
                        self.assertEqual(row[5] is None, baseline == 0)
                        snapshot = json.loads(
                            entry["submission"]["original_receipt"]
                        )
                        self.assertEqual(
                            snapshot["profiles"][0]["upload_bytes"],
                            baseline + len(payload),
                        )
                        self.assertEqual(
                            snapshot["profiles"][0]["download_bytes"],
                            baseline + len(payload),
                        )
                        baseline += len(payload)
                    effects = await fresh.execute(
                        text(
                            "SELECT s.status,s.used_bytes,t.state,p.applied"
                            "_generation,"
                            "(SELECT balance_rial FROM tbl_wallets WHERE cu"
                            "stomer_id=s.customer_id),"
                            "(SELECT COUNT(*) FROM tbl_wallet_entries e JOI"
                            "N tbl_wallets w "
                            "ON w.id=e.wallet_id WHERE w.customer_id=s.cust"
                            "omer_id AND e.reason='purchase'),"
                            "(SELECT COUNT(*) FROM tbl_managed_admissions W"
                            "HERE provision_task_id=t.id),"
                            "(SELECT COUNT(*) FROM tbl_managed_barriers),"
                            "(SELECT COUNT(*) FROM tbl_usage_events WHERE s"
                            "ubscription_id=s.id),"
                            "(SELECT COUNT(*) FROM tbl_usage_grants WHERE s"
                            "ubscription_id=s.id AND is_closed=0),"
                            "(SELECT COUNT(*) FROM tbl_notifications WHERE "
                            "event_key=:key) "
                            "FROM tbl_subscriptions s JOIN tbl_provision_ta"
                            "sks t ON t.id=:task "
                            "JOIN tbl_profiles p ON p.id=t.profile_id WHERE"
                            " s.id=:id"
                        ),
                        {
                            "id": subscription["id"],
                            "task": task_id,
                            "key": f"activation:{request_id}",
                        },
                    )
                    self.assertEqual(
                        tuple(effects.one()),
                        (
                            "active",
                            2 * sum(map(len, payloads)),
                            "applied",
                            0,
                            200000,
                            1,
                            1,
                            3,
                            3,
                            0,
                            1,
                        ),
                    )
                    events = await fresh.execute(
                        text(
                            "SELECT SUM(delta_bytes),SUM(final) FROM tbl_us"
                            "age_events "
                            "WHERE subscription_id=:id"
                        ),
                        {"id": subscription["id"]},
                    )
                    self.assertEqual(
                        tuple(events.one()), (2 * sum(map(len, payloads)), 3)
                    )
            finally:
                server.should_exit = True
                try:
                    await asyncio.wait_for(serving, timeout=10)
                finally:
                    listener.close()
                    await asyncio.to_thread(runtime.__exit__, None, None, None)
