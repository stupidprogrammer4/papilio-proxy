"""Pending purchase, native strict closure and exactly-once wallet refund."""

import asyncio
import os
import socket
import tempfile
from pathlib import Path

import uvicorn
from sqlalchemy import text

from tests.managed_installation_agent import actual_registry, compact, digest
from tests.managed_paid_revocation_agent import exercise_native_paid_revocation
from tests.real_core_runtime import RealCoreRuntime
from tests.test_managed_installation_workflow import (
    ManagedInstallationWorkflowFixture,
)


class ManagedPaidRevocationAgentWorkflowTest(
    ManagedInstallationWorkflowFixture
):
    paid_managed_fixture = True

    async def test_native_pending_purchase_revoke_finality_refund_once(self):
        runtime_binary = os.environ.get("PAPILIO_RUNTIME_TEST_BINARY")
        managed_binary = os.environ.get("PAPILIO_MANAGED_TEST_BINARY")
        binaries = os.environ.get("PAPILIO_CORE_BIN_DIR")
        if not runtime_binary or not managed_binary or not binaries:
            self.skipTest(
                "Explicit owned fresh agent/managed/stock binaries required"
            )
        assert runtime_binary and managed_binary and binaries
        self.settings.usage.policy.mode = "reserved"
        payload = b"native-unacknowledged-paid-window-refund"
        with tempfile.TemporaryDirectory(
            prefix="papilio-native-paid-revoke-"
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
                # Owning test policy budgets windows, admission receipts and
                # two artifacts for the single immutable revoke operation.
                windows = registry["registry"]["window_policy"]
                windows.update(
                    max_admission_receipts=8, max_revocations=1, max_records=18
                )
                registry["trusted_api_policy"][
                    "window_policy_sha256"
                ] = await asyncio.to_thread(
                    digest, compact(windows, canonical=True)
                )
                policy = self.settings.managed_adapter
                assert policy is not None
                self.settings.managed_adapter = policy.model_copy(
                    update={
                        **registry["trusted_api_policy"],
                        "window_mode": "reserved",
                        "paid_mode": "strict_admission",
                    }
                )
                issued = await self.issue()
                self.assertEqual(issued.status_code, 200)
                installation_id = issued.json()["data"]["id"]
                async with self.connection.uow() as fresh:
                    profile = await fresh.execute(
                        text(
                            "SELECT id FROM tbl_profiles WHERE "
                            "configuration_id=:configuration AND "
                            "subscription_id=:subscription"
                        ),
                        {
                            "configuration": configuration["id"],
                            "subscription": subscription["id"],
                        },
                    )
                    profile_id = profile.scalar_one()
                    task = await fresh.execute(
                        text(
                            "SELECT t.id,r.id FROM tbl_provision_tasks t JOIN "
                            "tbl_provision_requests r ON r.id=t.request_id "
                            "WHERE r.subscription_id=:id"
                        ),
                        {"id": subscription["id"]},
                    )
                    task_id, request_id = tuple(task.one())
                    pending = await fresh.execute(
                        text(
                            "SELECT status,activated_at,used_bytes FROM "
                            "tbl_subscriptions WHERE id=:id"
                        ),
                        {"id": subscription["id"]},
                    )
                    self.assertEqual(
                        tuple(pending.one()), ("pending_provision", None, 0)
                    )
                cookie = self.client.cookies.get("papilio_admin")
                assert cookie is not None
                result = await asyncio.to_thread(
                    exercise_native_paid_revocation,
                    root,
                    Path(runtime_binary),
                    registry["registry"],
                    installation_id,
                    profile_id,
                    task_id,
                    subscription,
                    f"http://127.0.0.1:{listener.getsockname()[1]}",
                    node,
                    {**self.headers, "Cookie": "papilio_admin=" + cookie},
                    Path(binaries),
                    payload=payload,
                )
                self.assertEqual(
                    (result.upload_bytes, result.download_bytes),
                    (len(payload), len(payload)),
                )
                self.assertTrue(
                    result.child_stopped and result.replay_unchanged
                )
                self.assertEqual(
                    (
                        result.wallet_balance_rial,
                        result.refund_count,
                        result.task_id,
                    ),
                    (300000, 1, task_id),
                )
                async with self.connection.uow() as fresh:
                    state = await fresh.execute(
                        text(
                            "SELECT "
                            "s.status,s.activated_at,s.used_bytes,r.state,"
                            "t.state,t.last_outcome,p.applied_generation FROM "
                            "tbl_subscriptions s JOIN tbl_provision_requests "
                            "r ON r.subscription_id=s.id JOIN "
                            "tbl_provision_tasks t ON t.request_id=r.id JOIN "
                            "tbl_profiles p ON p.id=t.profile_id WHERE "
                            "t.id=:id AND r.id=:request"
                        ),
                        {"id": task_id, "request": request_id},
                    )
                    self.assertEqual(
                        tuple(state.one()),
                        (
                            "failed",
                            None,
                            2 * len(payload),
                            "refunded",
                            "revoked",
                            "revoked",
                            None,
                        ),
                    )
                    grant = await fresh.execute(
                        text(
                            "SELECT "
                            "profile_id,subscription_id,process_epoch,"
                            "allocated_bytes,upload_bytes,download_bytes,"
                            "is_closed,sequence FROM tbl_usage_grants WHERE "
                            "id=:id"
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
                    events = await fresh.execute(
                        text(
                            "SELECT COUNT(*),SUM(delta_bytes),SUM(final) FROM "
                            "tbl_usage_events WHERE grant_id=:id"
                        ),
                        {"id": result.grant_id},
                    )
                    self.assertEqual(
                        tuple(events.one()), (1, 2 * len(payload), 1)
                    )
                    reservations = await fresh.execute(
                        text(
                            "SELECT COUNT(*) FROM tbl_usage_grants WHERE "
                            "subscription_id=:id AND mode='reserved' AND "
                            "is_closed=0"
                        ),
                        {"id": subscription["id"]},
                    )
                    self.assertEqual(reservations.scalar_one(), 0)
                    admissions = await fresh.execute(
                        text(
                            "SELECT COUNT(*) FROM tbl_managed_admissions "
                            "WHERE provision_task_id=:id"
                        ),
                        {"id": task_id},
                    )
                    self.assertEqual(admissions.scalar_one(), 0)
                    revocations = await fresh.execute(
                        text(
                            "SELECT COUNT(*),MIN(receipt_sha256) FROM "
                            "tbl_managed_revocations WHERE "
                            "provision_task_id=:id"
                        ),
                        {"id": task_id},
                    )
                    self.assertEqual(
                        tuple(revocations.one()), (1, result.revocation_sha256)
                    )
                    barriers = await fresh.execute(
                        text(
                            "SELECT COUNT(*),MIN(snapshot_sha256) FROM "
                            "tbl_managed_barriers"
                        )
                    )
                    self.assertEqual(
                        tuple(barriers.one()), (1, result.snapshot_sha256)
                    )
                    wallet = await fresh.execute(
                        text(
                            "SELECT "
                            "w.balance_rial,COUNT(e.id),"
                            "COALESCE(SUM(e.amount_rial),0) FROM tbl_wallets "
                            "w LEFT JOIN tbl_wallet_entries e ON "
                            "e.wallet_id=w.id AND e.reason='provision_refund' "
                            "WHERE w.customer_id=:id GROUP BY "
                            "w.id,w.balance_rial"
                        ),
                        {"id": subscription["customer_id"]},
                    )
                    self.assertEqual(tuple(wallet.one()), (300000, 1, 100000))
            finally:
                server.should_exit = True
                try:
                    await asyncio.wait_for(serving, timeout=10)
                finally:
                    listener.close()
                    await asyncio.to_thread(runtime.__exit__, None, None, None)
