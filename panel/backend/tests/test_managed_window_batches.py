"""Typed contracts for atomic managed-window batches."""

import asyncio
import hashlib
import json
import unittest
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import text

from src.modules.network.managed_runtime.app.window_computation import (
    compute_managed_window_batch_digest,
)
from src.modules.network.managed_runtime.app.window_encoding import (
    ManagedWindowEncoding,
)
from src.modules.network.managed_runtime.domain.admissions import (
    ManagedAdmissionOut,
)
from src.modules.network.managed_runtime.domain.barriers import (
    ManagedWindowFinalBatchCreate,
    ManagedWindowFinalBatchItemCreate,
)
from src.modules.network.managed_runtime.domain.windows import (
    ManagedInitialWindowBatchCreate,
    ManagedInitialWindowCreate,
)
from tests.test_managed_windows_workflow import ManagedWindowWorkflowFixture


def finality_batch_body(windows, expected, batch_request_key):
    items = []
    for window in windows:
        profile_id = window["binding"]["profile_id"]
        barrier_id = hashlib.sha256(str(profile_id).encode()).hexdigest()[:32]
        snapshot = {
            "installation": window["installation"],
            "epoch": window["epoch"],
            "barrier_id": barrier_id,
            "adapter_revision": expected["adapter_revision"],
            "source_commit": expected["source_commit"],
            "accounting_scope": "decoded_managed_tcp_payload_admission",
            "frozen_at": datetime.now(UTC).isoformat(),
            "profiles": [
                {
                    "binding": window["binding"],
                    "upload_bytes": window["baseline_upload_bytes"] + 120,
                    "download_bytes": window["baseline_download_bytes"] + 30,
                }
            ],
            "windows": [window],
            "enforcement": [
                {
                    "profile_id": profile_id,
                    "window_id": window["window_id"],
                    "allocated_bytes": window["allocated_bytes"],
                    "admitted_bytes": 150,
                    "closure_reason": "manual_freeze",
                }
            ],
        }
        original = json.dumps(snapshot, indent=2)
        items.append(
            {
                "window_id": window["window_id"],
                "request_key": f"final_item_{profile_id}",
                "submission": {
                    "original_receipt": original,
                    "receipt": {
                        "epoch": snapshot["epoch"],
                        "barrier_id": barrier_id,
                        "snapshot_sha256": hashlib.sha256(
                            original.encode()
                        ).hexdigest(),
                        "bytes": len(original.encode()),
                    },
                },
            }
        )
    return {
        "batch_request_key": batch_request_key,
        "windows": items,
    }


class ManagedInitialWindowBatchContractTest(unittest.TestCase):
    def test_managed_admission_output_requires_timezone_aware_utc(self):
        with self.assertRaises(ValidationError):
            ManagedAdmissionOut(
                window_id="a" * 32,
                provision_task_id=41,
                admission_sha256="b" * 64,
                observed_at=datetime(2026, 10, 16, 12, 0),
            )

    def test_batch_requires_unique_profile_identity_and_stable_key(self):
        item = ManagedInitialWindowCreate(
            profile_id=41,
            generation=2,
            process_epoch="a" * 32,
            request_key="window_41_2",
            requested_bytes=1024,
        )
        batch = ManagedInitialWindowBatchCreate(
            batch_request_key="batch_20261014_01", windows=[item]
        )
        self.assertEqual(batch.windows[0].profile_id, 41)
        with self.assertRaises(ValidationError):
            ManagedInitialWindowBatchCreate(
                batch_request_key="batch_20261014_01",
                windows=[item, item],
            )

    def test_finality_batch_requires_independent_receipts_and_keys(self):
        submission = {
            "original_receipt": "{}",
            "receipt": {
                "epoch": "a" * 32,
                "barrier_id": "b" * 32,
                "snapshot_sha256": "c" * 64,
                "bytes": 2,
            },
        }
        first = ManagedWindowFinalBatchItemCreate(
            window_id="d" * 32,
            request_key="finality_profile_41",
            submission=submission,
        )
        second = ManagedWindowFinalBatchItemCreate(
            window_id="e" * 32,
            request_key="finality_profile_52",
            submission={
                **submission,
                "receipt": {**submission["receipt"], "barrier_id": "f" * 32},
            },
        )

        batch = ManagedWindowFinalBatchCreate(
            batch_request_key="finality_batch_0001",
            windows=[first, second],
        )

        self.assertEqual(
            [item.window_id for item in batch.windows],
            ["d" * 32, "e" * 32],
        )
        with self.assertRaises(ValidationError):
            ManagedWindowFinalBatchCreate(
                batch_request_key="finality_batch_0002",
                windows=[first, first],
            )
        with self.assertRaises(ValidationError):
            ManagedWindowFinalBatchCreate(
                batch_request_key="finality_batch_0003",
                windows=[
                    first,
                    second.model_copy(
                        update={"request_key": first.request_key}
                    ),
                ],
            )
        with self.assertRaises(ValidationError):
            ManagedWindowFinalBatchCreate(
                batch_request_key="finality_batch_0004",
                windows=[
                    first,
                    ManagedWindowFinalBatchItemCreate(
                        window_id=second.window_id,
                        request_key=second.request_key,
                        submission=submission,
                    ),
                ],
            )

    def test_batch_request_digests_preserve_identity_and_single_contract(self):
        windows = tuple(
            ManagedInitialWindowCreate(
                profile_id=profile_id,
                generation=3,
                process_epoch="a" * 32,
                request_key=f"request_{profile_id:08}",
                requested_bytes=4096,
            )
            for profile_id in (41, 52)
        )

        digests = ManagedWindowEncoding.request_digests(7, windows)

        self.assertEqual(
            [
                (item.profile_id, item.generation, item.request_key)
                for item in digests
            ],
            [(41, 3, "request_00000041"), (52, 3, "request_00000052")],
        )
        self.assertEqual(
            [item.request_sha256 for item in digests],
            [
                ManagedWindowEncoding.request_digest(7, item)
                for item in windows
            ],
        )
        first = ManagedWindowEncoding.batch_request_digest(
            7, "batch_request_0001", windows
        )
        replay = ManagedWindowEncoding.batch_request_digest(
            7, "batch_request_0001", windows
        )
        changed = ManagedWindowEncoding.batch_request_digest(
            7, "batch_request_0002", windows
        )
        self.assertEqual(first, replay)
        self.assertNotEqual(first.request_sha256, changed.request_sha256)
        self.assertEqual(first.windows, digests)

    def test_digest_batch_yields_to_the_event_loop(self):
        windows = tuple(
            ManagedInitialWindowCreate(
                profile_id=profile_id,
                generation=3,
                process_epoch="a" * 32,
                request_key=f"request_{profile_id:08}",
                requested_bytes=4096,
            )
            for profile_id in (41, 52)
        )

        async def run():
            progressed = asyncio.Event()

            async def mark_progress():
                progressed.set()

            task = asyncio.create_task(mark_progress())
            batch = await compute_managed_window_batch_digest(
                7, "batch_request_0001", windows
            )
            self.assertTrue(progressed.is_set())
            self.assertEqual(len(batch.windows), len(windows))
            self.assertEqual(len(batch.request_sha256), 64)
            await task

        asyncio.run(run())


class ManagedInitialWindowBatchWorkflowTest(ManagedWindowWorkflowFixture):
    async def test_batch_leases_matching_paid_task_with_other_active_profile(
        self,
    ):
        self.add_second_managed_profile = True
        self.paid_managed_fixture = True
        (
            subscription,
            node,
            expected,
            first,
            path,
            _,
        ) = await self.setup_closed()
        policy = self.settings.managed_adapter
        assert policy is not None
        self.settings.managed_adapter = policy.model_copy(
            update={
                "window_mode": "reserved",
                "paid_mode": "strict_admission",
            }
        )
        async with self.connection.uow() as fresh:
            task = await fresh.execute(
                text(
                    "SELECT t.id,t.profile_id FROM tbl_provision_tasks t "
                    "JOIN tbl_provision_requests r ON r.id=t.request_id "
                    "WHERE r.subscription_id=:subscription"
                ),
                {"subscription": subscription["id"]},
            )
            task_id, paid_profile_id = tuple(task.one())
        profiles = [
            member["binding"]["profile_id"] for member in expected["profiles"]
        ]
        other_profile_id = next(
            profile_id
            for profile_id in profiles
            if profile_id != paid_profile_id
        )
        batch = {
            "batch_request_key": "paid_batch_" + self.suffix,
            "windows": [
                {
                    **first,
                    "profile_id": paid_profile_id,
                    "request_key": "paid_profile_" + self.suffix,
                    "provision_task_id": task_id,
                },
                {
                    **first,
                    "profile_id": other_profile_id,
                    "request_key": "active_profile_" + self.suffix,
                    "provision_task_id": None,
                },
            ],
        }
        response = await self.client.post(
            path + "/batch", headers=self.node_headers, json=batch
        )
        self.assertEqual(response.status_code, 200, response.text)
        windows = response.json()["data"]["windows"]
        by_profile = {item["profile_id"]: item["window"] for item in windows}
        self.assertEqual(
            by_profile[paid_profile_id]["provision_claim"]["task_id"], task_id
        )
        self.assertIsNone(by_profile[other_profile_id]["provision_claim"])
        async with self.connection.uow() as fresh:
            task_state = await fresh.execute(
                text(
                    "SELECT state,attempts,claim_hash "
                    "FROM tbl_provision_tasks "
                    "WHERE id=:id"
                ),
                {"id": task_id},
            )
            state, attempts, claim_hash = tuple(task_state.one())
            self.assertEqual((state, attempts), ("leased", 1))
            self.assertEqual(len(claim_hash), 64)

    async def test_two_profile_batch_is_atomic_and_exactly_replayable(self):
        self.add_second_managed_profile = True
        _, node, expected, first, path, _ = await self.setup_closed()
        policy = self.settings.managed_adapter
        assert policy is not None
        self.settings.managed_adapter = policy.model_copy(
            update={"window_mode": "reserved"}
        )
        profiles = [
            member["binding"]["profile_id"] for member in expected["profiles"]
        ]
        self.assertEqual(len(profiles), 2)
        batch = {
            "batch_request_key": "initial_batch_" + self.suffix,
            "windows": [
                {
                    **first,
                    "profile_id": profile_id,
                    "request_key": f"batch_profile_{profile_id}_{self.suffix}",
                }
                for profile_id in profiles
            ],
        }
        batch_path = path + "/batch"
        issued, concurrent_replay = await asyncio.gather(
            self.client.post(
                batch_path, headers=self.node_headers, json=batch
            ),
            self.client.post(
                batch_path, headers=self.node_headers, json=batch
            ),
        )
        self.assertEqual(issued.status_code, 200, issued.text)
        self.assertEqual(
            concurrent_replay.status_code, 200, concurrent_replay.text
        )
        first_result = issued.json()["data"]
        self.assertEqual(concurrent_replay.json()["data"], first_result)
        self.assertEqual(
            [item["profile_id"] for item in first_result["windows"]],
            profiles,
        )
        replay = await self.client.post(
            batch_path, headers=self.node_headers, json=batch
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["data"], first_result)
        unauthorized_batch = {
            **batch,
            "batch_request_key": batch["batch_request_key"] + "_scope",
            "windows": [
                batch["windows"][0],
                {
                    **batch["windows"][1],
                    "profile_id": 2**31,
                    "request_key": "outside_profile_" + self.suffix,
                },
            ],
        }
        unauthorized = await self.client.post(
            batch_path,
            headers=self.node_headers,
            json=unauthorized_batch,
        )
        self.assertEqual(unauthorized.status_code, 409, unauthorized.text)
        self.assertIn("managed_window_profile_invalid", unauthorized.text)
        changed = {
            **batch,
            "windows": [
                {**batch["windows"][0], "requested_bytes": 1025},
                batch["windows"][1],
            ],
        }
        conflict = await self.client.post(
            batch_path, headers=self.node_headers, json=changed
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertIn("managed_window_batch_reused", conflict.text)
        async with self.connection.uow() as fresh:
            counts = await fresh.execute(
                text(
                    "SELECT COUNT(*),SUM(allocated_bytes) "
                    "FROM tbl_usage_grants WHERE node_id=:node"
                ),
                {"node": node["node"]["id"]},
            )
            self.assertEqual(tuple(counts.one()), (2, 2048))
            batch_rows = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_managed_operation_batches "
                    "WHERE request_key=:key AND operation='initial_windows'"
                ),
                {"key": batch["batch_request_key"]},
            )
            self.assertEqual(batch_rows.scalar_one(), 1)

    async def test_window_insert_failure_rolls_back_grants_and_batch_record(
        self,
    ):
        self.add_second_managed_profile = True
        _, node, expected, first, path, _ = await self.setup_closed()
        policy = self.settings.managed_adapter
        assert policy is not None
        self.settings.managed_adapter = policy.model_copy(
            update={"window_mode": "reserved"}
        )
        profiles = [
            member["binding"]["profile_id"] for member in expected["profiles"]
        ]
        batch = {
            "batch_request_key": "rollback_batch_" + self.suffix,
            "windows": [
                {
                    **first,
                    "profile_id": profile_id,
                    "request_key": (
                        f"rollback_profile_{profile_id}_{self.suffix}"
                    ),
                }
                for profile_id in profiles
            ],
        }
        failing_profile_id = profiles[-1]
        async with self.connection.uow() as setup:
            await setup.execute(
                text(
                    "CREATE TRIGGER force_managed_window_batch_insert_failure "
                    "BEFORE INSERT ON tbl_managed_windows FOR EACH ROW "
                    f"BEGIN IF NEW.profile_id = "
                    f"{int(failing_profile_id)} THEN "
                    "SIGNAL SQLSTATE '45000' "
                    "SET MESSAGE_TEXT = 'injected batch insert failure'; "
                    "END IF; END"
                )
            )
        try:
            response = await self.client.post(
                path + "/batch", headers=self.node_headers, json=batch
            )
        except Exception as error:
            self.assertIn("injected batch insert failure", str(error))
            response = None
        if response is not None:
            self.assertGreaterEqual(response.status_code, 400, response.text)
        async with self.connection.uow() as fresh:
            grants = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_usage_grants WHERE node_id=:node"
                ),
                {"node": node["node"]["id"]},
            )
            windows = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_managed_windows "
                    "WHERE request_key LIKE :prefix"
                ),
                {"prefix": "rollback_profile_%"},
            )
            batches = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_managed_operation_batches "
                    "WHERE request_key=:request_key"
                ),
                {"request_key": batch["batch_request_key"]},
            )
            self.assertEqual(grants.scalar_one(), 0)
            self.assertEqual(windows.scalar_one(), 0)
            self.assertEqual(batches.scalar_one(), 0)

    async def test_finality_batch_settles_and_replays_independent_snapshots(
        self,
    ):
        self.add_second_managed_profile = True
        (
            _,
            node,
            expected,
            first,
            path,
            _,
        ) = await self.setup_closed()
        policy = self.settings.managed_adapter
        assert policy is not None
        self.settings.managed_adapter = policy.model_copy(
            update={"window_mode": "reserved"}
        )
        profiles = [
            member["binding"]["profile_id"] for member in expected["profiles"]
        ]
        issue_body = {
            "batch_request_key": "finality_issue_" + self.suffix,
            "windows": [
                {
                    **first,
                    "profile_id": profile_id,
                    "request_key": (
                        f"finality_profile_{profile_id}_{self.suffix}"
                    ),
                }
                for profile_id in profiles
            ],
        }
        issued = await self.client.post(
            path + "/batch", headers=self.node_headers, json=issue_body
        )
        self.assertEqual(issued.status_code, 200, issued.text)
        windows = [
            item["window"]["window"]
            for item in issued.json()["data"]["windows"]
        ]
        body = finality_batch_body(
            windows,
            expected,
            "finality_batch_" + self.suffix,
        )
        original = body["windows"][0]["submission"]["original_receipt"]
        finality_path = (
            f"/v1/nodes/{node['node']['code']}/managed-windows/finalize/batch"
        )
        accepted, concurrent_replay = await asyncio.gather(
            self.client.post(
                finality_path, headers=self.node_headers, json=body
            ),
            self.client.post(
                finality_path, headers=self.node_headers, json=body
            ),
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(
            concurrent_replay.status_code,
            200,
            concurrent_replay.text,
        )
        self.assertEqual(
            concurrent_replay.json()["data"], accepted.json()["data"]
        )
        replay = await self.client.post(
            finality_path, headers=self.node_headers, json=body
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["data"], accepted.json()["data"])
        changed_original = original + " "
        changed_first = body["windows"][0]
        changed = {
            **body,
            "windows": [
                {
                    **changed_first,
                    "submission": {
                        "original_receipt": changed_original,
                        "receipt": {
                            **changed_first["submission"]["receipt"],
                            "snapshot_sha256": hashlib.sha256(
                                changed_original.encode()
                            ).hexdigest(),
                            "bytes": len(changed_original.encode()),
                        },
                    },
                },
                *body["windows"][1:],
            ],
        }
        conflict = await self.client.post(
            finality_path, headers=self.node_headers, json=changed
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)
        results = accepted.json()["data"]["windows"]
        self.assertEqual(
            [row["window_id"] for row in results],
            [item["window_id"] for item in body["windows"]],
        )
        grant_ids = [window["grant_id"] for window in windows]
        grant_params = {
            f"grant_{index}": value for index, value in enumerate(grant_ids)
        }
        grant_placeholders = ",".join(
            f":grant_{index}" for index in range(len(grant_ids))
        )
        async with self.connection.uow() as fresh:
            grants = await fresh.execute(
                text(
                    "SELECT COUNT(*),SUM(is_closed),SUM(upload_bytes),"
                    "SUM(download_bytes) FROM tbl_usage_grants WHERE "
                    f"id IN ({grant_placeholders})"
                ),
                grant_params,
            )
            self.assertEqual(
                tuple(grants.one()),
                (2, 2, 240, 60),
                f"grant_ids={grant_ids}",
            )
            usage = await fresh.execute(
                text(
                    "SELECT SUM(s.used_bytes) FROM tbl_subscriptions s "
                    "JOIN tbl_usage_grants g ON g.subscription_id=s.id "
                    f"WHERE g.id IN ({grant_placeholders})"
                ),
                grant_params,
            )
            self.assertEqual(usage.scalar_one(), 300)
            events = await fresh.execute(
                text(
                    "SELECT COUNT(*),SUM(delta_bytes) FROM tbl_usage_events "
                    f"WHERE grant_id IN ({grant_placeholders})"
                ),
                grant_params,
            )
            self.assertEqual(tuple(events.one()), (2, 300))
            barriers = await fresh.execute(
                text("SELECT COUNT(*) FROM tbl_managed_barriers")
            )
            self.assertEqual(barriers.scalar_one(), 2)
            batches = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_managed_operation_batches "
                    "WHERE request_key=:key AND operation='final_windows'"
                ),
                {"key": body["batch_request_key"]},
            )
            self.assertEqual(batches.scalar_one(), 1)

    async def test_finality_failure_rolls_back_every_batch_effect(self):
        self.add_second_managed_profile = True
        _, node, expected, first, path, _ = await self.setup_closed()
        policy = self.settings.managed_adapter
        assert policy is not None
        self.settings.managed_adapter = policy.model_copy(
            update={"window_mode": "reserved"}
        )
        profiles = [
            member["binding"]["profile_id"] for member in expected["profiles"]
        ]
        issue_body = {
            "batch_request_key": "rollback_finality_issue_" + self.suffix,
            "windows": [
                {
                    **first,
                    "profile_id": profile_id,
                    "request_key": (
                        f"rollback_finality_{profile_id}_{self.suffix}"
                    ),
                }
                for profile_id in profiles
            ],
        }
        issued = await self.client.post(
            path + "/batch", headers=self.node_headers, json=issue_body
        )
        self.assertEqual(issued.status_code, 200, issued.text)
        windows = [
            item["window"]["window"]
            for item in issued.json()["data"]["windows"]
        ]
        body = finality_batch_body(
            windows,
            expected,
            "rollback_finality_batch_" + self.suffix,
        )
        grant_ids = [window["grant_id"] for window in windows]
        grant_params = {
            f"grant_{index}": value for index, value in enumerate(grant_ids)
        }
        grant_placeholders = ",".join(
            f":grant_{index}" for index in range(len(grant_ids))
        )
        async with self.connection.uow() as setup:
            await setup.execute(
                text(
                    "CREATE TRIGGER force_final_batch_operation_failure "
                    "BEFORE INSERT ON tbl_managed_operation_batches "
                    "FOR EACH ROW BEGIN IF NEW.operation = 'final_windows' "
                    "THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = "
                    "'injected final batch failure'; END IF; END"
                )
            )
        finality_path = (
            f"/v1/nodes/{node['node']['code']}/managed-windows/finalize/batch"
        )
        try:
            await self.client.post(
                finality_path, headers=self.node_headers, json=body
            )
        except Exception as error:
            self.assertIn("injected final batch failure", str(error))
        else:
            self.fail("Injected late write failure was not raised")
        async with self.connection.uow() as fresh:
            grants = await fresh.execute(
                text(
                    "SELECT COUNT(*),SUM(is_closed),SUM(upload_bytes),"
                    "SUM(download_bytes) FROM tbl_usage_grants WHERE "
                    f"id IN ({grant_placeholders})"
                ),
                grant_params,
            )
            self.assertEqual(tuple(grants.one()), (2, 0, 0, 0))
            events = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_usage_events WHERE "
                    f"grant_id IN ({grant_placeholders})"
                ),
                grant_params,
            )
            usage = await fresh.execute(
                text(
                    "SELECT SUM(s.used_bytes) FROM tbl_subscriptions s "
                    "JOIN tbl_usage_grants g ON g.subscription_id=s.id "
                    f"WHERE g.id IN ({grant_placeholders})"
                ),
                grant_params,
            )
            barriers = await fresh.execute(
                text("SELECT COUNT(*) FROM tbl_managed_barriers")
            )
            batches = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_managed_operation_batches "
                    "WHERE request_key=:key AND operation='final_windows'"
                ),
                {"key": body["batch_request_key"]},
            )
            self.assertEqual(events.scalar_one(), 0)
            self.assertEqual(usage.scalar_one(), 0)
            self.assertEqual(barriers.scalar_one(), 0)
            self.assertEqual(batches.scalar_one(), 0)

    def test_batch_cannot_be_empty_or_reuse_a_short_key(self):
        with self.assertRaises(ValidationError):
            ManagedInitialWindowBatchCreate(
                batch_request_key="stable_batch_key", windows=[]
            )

        with self.assertRaises(ValidationError):
            ManagedInitialWindowBatchCreate(
                batch_request_key="short", windows=[]
            )


if __name__ == "__main__":
    unittest.main()
