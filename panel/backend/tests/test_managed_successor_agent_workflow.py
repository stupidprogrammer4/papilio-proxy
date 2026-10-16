"""Paid TLS windows, epoch rollover and durable response-loss recovery."""

import asyncio
import json
import os
import socket
import tempfile
from pathlib import Path

import uvicorn
from sqlalchemy import text

from src.modules.network.managed_runtime.domain.epoch_seals import (
    ManagedEpochSealLimits,
    ManagedEpochSealPolicy,
)
from src.modules.network.managed_runtime.domain.successors import (
    ManagedSuccessorLimits,
    ManagedSuccessorPolicy,
)
from tests.managed_epoch_fault_relay import ManagedRolloverResponseDrop
from tests.managed_installation_agent import actual_registry, compact, digest
from tests.managed_successor_agent import (
    ManagedBatchProfileInput,
    run_native_managed_window_batch,
    run_native_successor_cycles,
)
from tests.real_core_runtime import RealCoreRuntime
from tests.test_managed_installation_workflow import (
    ManagedInstallationWorkflowFixture,
)


class ManagedSuccessorAgentWorkflowTest(ManagedInstallationWorkflowFixture):
    paid_managed_fixture = True

    async def test_actual_paid_windows_survive_epoch_rollover_and_replay(self):
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
            b"paid-native-second-epoch-initial-window-proof",
            b"paid-native-second-epoch-first-successor-proof",
            b"paid-native-second-epoch-second-successor-proof",
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
                        "max_records": 24,
                        "max_admission_receipts": 8,
                    }
                )
                registry["registry"]["component_policy"]["max_barriers"] = 8
                registry["registry"]["window_policy"]["max_epoch_seals"] = 2
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
                        "epoch_seal_policy": ManagedEpochSealPolicy(
                            mode="strict",
                            limits=ManagedEpochSealLimits(
                                max_windows_per_epoch=8,
                                max_receipt_bytes=131072,
                                max_epochs=2,
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
                api_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
                with ManagedRolloverResponseDrop(api_url) as relay:
                    try:
                        result = await asyncio.to_thread(
                            run_native_successor_cycles,
                            root,
                            Path(runtime_binary),
                            registry["registry"],
                            installation_id,
                            profile_id,
                            relay.url,
                            node,
                            Path(binaries),
                            task_id,
                            payloads,
                            freeze_after_ms=8000,
                            max_epochs=2,
                        )
                    except AssertionError as error:
                        raise AssertionError(
                            f"{error}:relay={relay.events()}"
                        ) from error
                    rollover_responses = relay.rollover_responses()
                self.assertEqual(len(rollover_responses), 2)
                self.assertEqual(
                    rollover_responses[0][0], rollover_responses[1][0]
                )
                self.assertEqual(
                    rollover_responses[0][1:], rollover_responses[1][1:]
                )
                self.assertTrue(
                    result.replay_unchanged and result.child_stopped
                )
                entries = result.entries
                self.assertEqual(len(entries), 6)
                self.assertEqual(
                    len({e["issued"]["window"]["window_id"] for e in entries}),
                    6,
                )
                self.assertEqual(
                    len({e["issued"]["window"]["epoch"] for e in entries}), 2
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
                    self.assertEqual(len(rows), 6)
                    baseline = 0
                    for index, (row, entry, payload) in enumerate(
                        zip(rows, entries, payloads, strict=True)
                    ):
                        if index % 3 == 0:
                            baseline = 0
                        expected_task_id = task_id if index < 3 else None
                        self.assertEqual(
                            tuple(row[:5]),
                            (
                                entry["issued"]["window"]["window_id"],
                                entry["issued"]["window"]["grant_id"],
                                expected_task_id,
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
                            6,
                            6,
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
                        tuple(events.one()), (2 * sum(map(len, payloads)), 6)
                    )
                    epoch_counts = await fresh.execute(
                        text(
                            "SELECT COUNT(*) FROM tbl_managed_epoches "
                            "WHERE installation_id=:id"
                        ),
                        {"id": installation_id},
                    )
                    self.assertEqual(epoch_counts.scalar_one(), 2)
                    rollover_count = await fresh.execute(
                        text(
                            "SELECT COUNT(*) FROM tbl_managed_epoches "
                            "WHERE installation_id=:id "
                            "AND previous_epoch_id IS NOT NULL"
                        ),
                        {"id": installation_id},
                    )
                    self.assertEqual(rollover_count.scalar_one(), 1)
            finally:
                server.should_exit = True
                try:
                    await asyncio.wait_for(serving, timeout=10)
                finally:
                    listener.close()
                    await asyncio.to_thread(runtime.__exit__, None, None, None)

    async def test_actual_two_profile_batch_enforces_quota_expiry_and_rollover(
        self,
    ):
        runtime_binary = os.environ.get("PAPILIO_RUNTIME_TEST_BINARY")
        managed_binary = os.environ.get("PAPILIO_MANAGED_TEST_BINARY")
        binaries = os.environ.get("PAPILIO_CORE_BIN_DIR")
        if not runtime_binary or not managed_binary or not binaries:
            self.skipTest(
                "Explicit owned fresh agent/managed/stock binaries required"
            )
        assert runtime_binary and managed_binary and binaries
        self.add_second_managed_profile = True
        self.settings.usage.policy.mode = "reserved"
        validity_ms = 60000
        freeze_after_ms = 65000
        with tempfile.TemporaryDirectory(
            prefix="papilio-native-window-batch-"
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
                    purchased_subscription,
                    node,
                    configuration,
                ) = await self.setup_installation(inputs, runtime.port())
                async with self.connection.uow() as fresh:
                    rows = await fresh.execute(
                        text(
                            "SELECT p.id AS profile_id, "
                            "p.subscription_id AS subscription_id, "
                            "t.id AS task_id "
                            "FROM tbl_profiles p "
                            "LEFT JOIN tbl_provision_tasks t "
                            "ON t.profile_id=p.id AND t.action='apply' "
                            "WHERE p.configuration_id=:configuration "
                            "ORDER BY p.id"
                        ),
                        {"configuration": configuration["id"]},
                    )
                    profile_rows = tuple(rows.all())
                self.assertEqual(len(profile_rows), 2)
                purchased = [
                    row
                    for row in profile_rows
                    if row.subscription_id == purchased_subscription["id"]
                ]
                self.assertEqual(len(purchased), 1)
                (purchased_profile,) = purchased
                self.assertIsNotNone(purchased_profile.task_id)
                profiles = tuple(
                    ManagedBatchProfileInput(
                        profile_id=row.profile_id,
                        generation=0,
                        provision_task_id=int(row.task_id or 0),
                        requested_bytes=(
                            64
                            if row.subscription_id
                            == purchased_subscription["id"]
                            else 65536
                        ),
                    )
                    for row in profile_rows
                )
                registry = await asyncio.to_thread(
                    actual_registry,
                    root,
                    inputs,
                    Path(managed_binary),
                )
                registry["registry"]["window_policy"].update(
                    {
                        "max_windows": 4,
                        "max_records": 12,
                        "max_admission_receipts": 4,
                        "max_validity_ms": validity_ms,
                        "max_epoch_seals": 2,
                    }
                )
                registry["registry"]["component_policy"]["max_barriers"] = 8
                registry["trusted_api_policy"]["window_policy_sha256"] = (
                    digest(
                        compact(
                            registry["registry"]["window_policy"],
                            canonical=True,
                        )
                    )
                )
                policy = self.settings.managed_adapter
                assert policy is not None and policy.capacity is not None
                capacity = policy.capacity.model_copy(
                    update={
                        "max_validity_ms": validity_ms,
                        "max_window_bytes": 131072,
                    }
                )
                self.settings.managed_adapter = policy.model_copy(
                    update={
                        **registry["trusted_api_policy"],
                        "capacity": capacity,
                        "window_mode": "reserved",
                        "paid_mode": "strict_admission",
                        "epoch_seal_policy": ManagedEpochSealPolicy(
                            mode="strict",
                            limits=ManagedEpochSealLimits(
                                max_windows_per_epoch=4,
                                max_receipt_bytes=131072,
                                max_epochs=2,
                            ),
                        ),
                    }
                )
                issued = await self.issue()
                self.assertEqual(issued.status_code, 200, issued.text)
                installation_id = issued.json()["data"]["id"]
                api_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
                result = await asyncio.to_thread(
                    run_native_managed_window_batch,
                    root,
                    Path(runtime_binary),
                    registry,
                    installation_id,
                    profiles,
                    api_url,
                    node,
                    Path(binaries),
                    freeze_after_ms=freeze_after_ms,
                    validity_ms=validity_ms,
                )
                self.assertTrue(
                    result.independent_traffic
                    and result.quota_closed
                    and result.expiry_closed
                )
                self.assertEqual(len(result.entries), 4)
                self.assertEqual(
                    len(
                        {
                            entry["issued"]["window"]["window_id"]
                            for entry in result.entries
                        }
                    ),
                    4,
                )
                self.assertEqual(
                    len(
                        {
                            entry["issued"]["window"]["epoch"]
                            for entry in result.entries
                        }
                    ),
                    2,
                )
                purchased_profile_id = purchased_profile.profile_id
                for entry in result.entries:
                    profile_id = entry["issued"]["window"]["binding"][
                        "profile_id"
                    ]
                    finality = entry["finality"]
                    if profile_id == purchased_profile_id:
                        self.assertEqual(
                            (
                                finality["upload_bytes"],
                                finality["download_bytes"],
                            ),
                            (32, 32),
                        )
                    else:
                        self.assertGreater(finality["upload_bytes"], 0)
                        self.assertGreater(finality["download_bytes"], 0)
                async with self.connection.uow() as fresh:
                    grants = await fresh.execute(
                        text(
                            "SELECT p.id,g.allocated_bytes,g.upload_bytes,"
                            "g.download_bytes,g.is_closed,g.sequence "
                            "FROM tbl_managed_windows w "
                            "JOIN tbl_usage_grants g ON g.id=w.grant_id "
                            "JOIN tbl_profiles p ON p.id=w.profile_id "
                            "WHERE p.configuration_id=:configuration "
                            "ORDER BY w.id"
                        ),
                        {"configuration": configuration["id"]},
                    )
                    grant_rows = tuple(grants.all())
                    self.assertEqual(len(grant_rows), 4)
                    self.assertTrue(
                        all(
                            row.is_closed and row.sequence == 1
                            for row in grant_rows
                        )
                    )
                    purchases = await fresh.execute(
                        text(
                            "SELECT COUNT(*) FROM tbl_wallet_entries e "
                            "JOIN tbl_wallets w ON w.id=e.wallet_id "
                            "JOIN tbl_subscriptions s "
                            "ON s.customer_id=w.customer_id "
                            "WHERE s.id=:subscription "
                            "AND e.reason='purchase'"
                        ),
                        {"subscription": purchased_subscription["id"]},
                    )
                    self.assertEqual(purchases.scalar_one(), 1)
                    events = await fresh.execute(
                        text(
                            "SELECT COUNT(*),SUM(final) "
                            "FROM tbl_usage_events WHERE subscription_id IN ("
                            "SELECT subscription_id FROM tbl_profiles "
                            "WHERE configuration_id=:configuration)"
                        ),
                        {"configuration": configuration["id"]},
                    )
                    self.assertEqual(tuple(events.one()), (4, 4))
                    epochs = await fresh.execute(
                        text(
                            "SELECT COUNT(*), "
                            "SUM(previous_epoch_id IS NOT NULL) "
                            "FROM tbl_managed_epoches "
                            "WHERE installation_id=:installation"
                        ),
                        {"installation": installation_id},
                    )
                    self.assertEqual(tuple(epochs.one()), (2, 1))
            finally:
                server.should_exit = True
                try:
                    await asyncio.wait_for(serving, timeout=10)
                finally:
                    listener.close()
                    await asyncio.to_thread(runtime.__exit__, None, None, None)
