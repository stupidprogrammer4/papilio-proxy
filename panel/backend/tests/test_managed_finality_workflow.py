"""Native accounting with explicitly constructed external frozen receipts."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime

from papilio.infra.db.transaction import transaction
from sqlalchemy import text

from tests.test_managed_windows_workflow import ManagedWindowWorkflowFixture


class ManagedFinalityWorkflowTest(ManagedWindowWorkflowFixture):
    def frozen_submission(self, window, expectation, **changes):
        wire = window["window"]
        snapshot = {
            "installation": wire["installation"],
            "epoch": wire["epoch"],
            "barrier_id": "f" * 32,
            "adapter_revision": expectation["adapter_revision"],
            "source_commit": expectation["source_commit"],
            "accounting_scope": "decoded_managed_tcp_payload_admission",
            "frozen_at": datetime.now(UTC).isoformat(),
            "profiles": [
                {
                    "binding": wire["binding"],
                    "upload_bytes": 120,
                    "download_bytes": 30,
                    "unadmitted_upload_bytes": 1000,
                    "unadmitted_download_bytes": 2000,
                }
            ],
            "windows": [wire],
            "enforcement": [
                {
                    "profile_id": wire["binding"]["profile_id"],
                    "window_id": wire["window_id"],
                    "allocated_bytes": wire["allocated_bytes"],
                    "admitted_bytes": 150,
                    "closure_reason": "manual_freeze",
                }
            ],
            **changes,
        }
        original = json.dumps(snapshot, indent=2)
        return {
            "original_receipt": original,
            "receipt": {
                "epoch": wire["epoch"],
                "barrier_id": snapshot["barrier_id"],
                "snapshot_sha256": hashlib.sha256(
                    original.encode()
                ).hexdigest(),
                "bytes": len(original.encode()),
            },
        }

    async def assert_settlement(self, subscription, window, expected_usage):
        async with self.connection.uow() as fresh:
            grant = await fresh.execute(
                text(
                    "SELECT upload_bytes,download_bytes,is_closed "
                    "FROM tbl_usage_grants WHERE id=:id"
                ),
                {"id": window["window"]["grant_id"]},
            )
            self.assertEqual(tuple(grant.one()), (120, 30, True))
            used = await fresh.execute(
                text("SELECT used_bytes FROM tbl_subscriptions WHERE id=:id"),
                {"id": subscription["id"]},
            )
            self.assertEqual(used.scalar_one(), expected_usage)
            events = await fresh.execute(
                text(
                    "SELECT COUNT(*),SUM(delta_bytes) FROM tbl_usage_events "
                    "WHERE grant_id=:id"
                ),
                {"id": window["window"]["grant_id"]},
            )
            self.assertEqual(tuple(events.one()), (1, 150))
            barriers = await fresh.execute(
                text("SELECT COUNT(*) FROM tbl_managed_barriers")
            )
            self.assertEqual(barriers.scalar_one(), 1)

    async def test_exact_receipt_concurrent_replay_and_disabled_recovery(self):
        subscription, node, window, expected, _, _ = await self.setup_window()
        path = (
            f"/v1/nodes/{node['node']['code']}/managed-windows/"
            f"{window['window']['window_id']}/finalize"
        )
        body = self.frozen_submission(window, expected)
        bad = {**body, "original_receipt": body["original_receipt"] + " "}
        denied = await self.client.post(
            path, headers=self.node_headers, json=bad
        )
        self.assertEqual(denied.status_code, 409, denied.text)
        metadata = self.frozen_submission(window, expected, enforcement=[])
        denied = await self.client.post(
            path, headers=self.node_headers, json=metadata
        )
        self.assertEqual(denied.status_code, 409, denied.text)
        # Disabling new issuance must not lose recoverable final accounting.
        self.settings.managed_adapter = None
        responses = await asyncio.gather(
            self.client.post(path, headers=self.node_headers, json=body),
            self.client.post(path, headers=self.node_headers, json=body),
        )
        self.assertEqual([row.status_code for row in responses], [200, 200])
        self.assertEqual(
            responses[0].json()["data"], responses[1].json()["data"]
        )
        await self.assert_settlement(subscription, window, 150)
        changed = self.frozen_submission(window, expected)
        conflict = await self.client.post(
            path, headers=self.node_headers, json=changed
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)
        await self.assert_settlement(subscription, window, 150)

    async def test_final_old_generation_does_not_consume_renewed_quota(self):
        subscription, node, window, expected, _, _ = await self.setup_window()
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    text(
                        "UPDATE tbl_subscriptions SET renewal_count=1,"
                        "used_bytes=700 WHERE id=:id"
                    ),
                    {"id": subscription["id"]},
                )
        path = (
            f"/v1/nodes/{node['node']['code']}/managed-windows/"
            f"{window['window']['window_id']}/finalize"
        )
        accepted = await self.client.post(
            path,
            headers=self.node_headers,
            json=self.frozen_submission(window, expected),
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        await self.assert_settlement(subscription, window, 700)
