"""Actual native managed traffic/finality; activation is an explicit fixture.

The paid wallet purchase is native. ACTIVE/unmanaged entitlement is supplied by
ManagedInstallationWorkflowFixture; paid provisioning ACK is not proved.
"""

import asyncio
import os
import socket
import tempfile
from pathlib import Path

import uvicorn
from sqlalchemy import text

from tests.managed_installation_agent import actual_registry, compact, digest
from tests.managed_window_agent import run_native_window_cycle
from tests.real_core_runtime import RealCoreRuntime
from tests.test_managed_installation_workflow import (
    ManagedInstallationWorkflowFixture,
)


class ManagedWindowAgentWorkflowTest(ManagedInstallationWorkflowFixture):
    async def test_actual_native_agent_stock_tls_finality_and_replay(self):
        runtime_binary = os.environ.get("PAPILIO_RUNTIME_TEST_BINARY")
        managed_binary = os.environ.get("PAPILIO_MANAGED_TEST_BINARY")
        binaries = os.environ.get("PAPILIO_CORE_BIN_DIR")
        if not runtime_binary or not managed_binary or not binaries:
            self.skipTest(
                "Explicit owned fresh agent/managed/stock binaries required"
            )
        assert runtime_binary and managed_binary and binaries
        self.settings.usage.policy.mode = "reserved"
        payload = b"native-managed-window-finality-proof"
        with tempfile.TemporaryDirectory(
            prefix="papilio-native-window-"
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
                registry["registry"]["window_policy"][
                    "max_admission_receipts"
                ] = 8
                registry["trusted_api_policy"][
                    "window_policy_sha256"
                ] = await asyncio.to_thread(
                    digest,
                    compact(
                        registry["registry"]["window_policy"],
                        canonical=True,
                    ),
                )
                policy = self.settings.managed_adapter
                assert policy is not None
                self.settings.managed_adapter = policy.model_copy(
                    update={
                        **registry["trusted_api_policy"],
                        "window_mode": "reserved",
                    }
                )
                issued = await self.issue()
                self.assertEqual(issued.status_code, 200, issued.text)
                installation_id = issued.json()["data"]["id"]
                async with self.connection.uow() as fresh:
                    profiles = await fresh.execute(
                        text(
                            "SELECT id FROM tbl_profiles WHERE "
                            "configuration_id=:configuration "
                            "AND subscription_id=:subscription"
                        ),
                        {
                            "configuration": configuration["id"],
                            "subscription": subscription["id"],
                        },
                    )
                    profile_id = profiles.scalar_one()
                    before = await fresh.execute(
                        text(
                            "SELECT used_bytes FROM tbl_subscriptions "
                            "WHERE id=:id"
                        ),
                        {"id": subscription["id"]},
                    )
                    self.assertEqual(before.scalar_one(), 0)
                result = await asyncio.to_thread(
                    run_native_window_cycle,
                    root,
                    Path(runtime_binary),
                    registry["registry"],
                    installation_id,
                    profile_id,
                    f"http://127.0.0.1:{listener.getsockname()[1]}",
                    node,
                    Path(binaries),
                    freeze_after_ms=10000,
                    payload=payload,
                )
                self.assertEqual(result.upload_bytes, len(payload))
                self.assertEqual(result.download_bytes, len(payload))
                self.assertTrue(
                    result.replay_unchanged and result.child_stopped
                )
                self.assertEqual(len(result.admission_sha256), 64)
                async with self.connection.uow() as fresh:
                    grant = await fresh.execute(
                        text(
                            "SELECT profile_id,subscription_id,process_epoch,"
                            "allocated_bytes,upload_bytes,download_bytes,"
                            "is_closed,sequence "
                            "FROM tbl_usage_grants WHERE id=:id"
                        ),
                        {"id": result.grant_id},
                    )
                    self.assertEqual(
                        tuple(grant.one()),
                        (
                            profile_id,
                            subscription["id"],
                            result.epoch,
                            1024,
                            len(payload),
                            len(payload),
                            True,
                            1,
                        ),
                    )
                    used = await fresh.execute(
                        text(
                            "SELECT used_bytes FROM tbl_subscriptions "
                            "WHERE id=:id"
                        ),
                        {"id": subscription["id"]},
                    )
                    self.assertEqual(used.scalar_one(), 2 * len(payload))
                    events = await fresh.execute(
                        text(
                            "SELECT COUNT(*),SUM(delta_bytes),SUM(final) "
                            "FROM tbl_usage_events WHERE grant_id=:id"
                        ),
                        {"id": result.grant_id},
                    )
                    self.assertEqual(
                        tuple(events.one()), (1, 2 * len(payload), 1)
                    )
                    remaining = await fresh.execute(
                        text(
                            "SELECT COUNT(*),COALESCE(SUM(allocated_bytes),0) "
                            "FROM tbl_usage_grants WHERE subscription_id=:id "
                            "AND mode='reserved' AND is_closed=0"
                        ),
                        {"id": subscription["id"]},
                    )
                    self.assertEqual(tuple(remaining.one()), (0, 0))
                    barriers = await fresh.execute(
                        text(
                            "SELECT COUNT(*),MIN(snapshot_sha256) "
                            "FROM tbl_managed_barriers"
                        )
                    )
                    self.assertEqual(
                        tuple(barriers.one()), (1, result.receipt_sha256)
                    )
                    windows = await fresh.execute(
                        text("SELECT COUNT(*) FROM tbl_managed_windows")
                    )
                    self.assertEqual(windows.scalar_one(), 1)
                    admissions = await fresh.execute(
                        text("SELECT COUNT(*) FROM tbl_managed_admissions")
                    )
                    self.assertEqual(admissions.scalar_one(), 0)
            finally:
                server.should_exit = True
                try:
                    await asyncio.wait_for(serving, timeout=10)
                finally:
                    listener.close()
                    await asyncio.to_thread(runtime.__exit__, None, None, None)
