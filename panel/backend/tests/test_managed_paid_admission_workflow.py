"""Native paid activation with an explicit external admission reporter."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime

from papilio.infra.db.transaction import transaction
from sqlalchemy import text

from tests import test_managed_finality_workflow as final_reporter
from tests.test_managed_windows_workflow import ManagedWindowWorkflowFixture


class ManagedPaidAdmissionWorkflowTest(ManagedWindowWorkflowFixture):
    paid_managed_fixture = True

    async def test_refund_requires_finality_and_original_revocation(self):
        (
            subscription,
            task_id,
            request_id,
            issued,
            admission,
            path,
        ) = await self.paid_window()
        expected = json.loads(admission["original_receipt"])
        final = final_reporter.ManagedFinalityWorkflowTest.frozen_submission(
            issued, expected
        )
        revocation_document = {
            "receipt_version": 1,
            "state": "historical_epoch_profile_revoked",
            "request": {
                "epoch": issued["window"]["epoch"],
                "request_id": "b" * 32,
                "barrier_id": "f" * 32,
                "window_id": issued["window"]["window_id"],
                "binding": issued["window"]["binding"],
            },
            "window": issued["window"],
            "installation": issued["window"]["installation"],
            "snapshot": final["receipt"],
            "adapter_revision": expected["adapter_revision"],
            "source_commit": expected["source_commit"],
            "module": expected["module"],
            "accounting_scope": expected["accounting_scope"],
            "startup_receipt_sha256": expected["startup_receipt_sha256"],
            "window_policy_sha256": expected["window_policy_sha256"],
            "observed_at": datetime.now(UTC).isoformat(),
            "admission_blocked": True,
            "historical_only": True,
            "api_authority": False,
        }
        original = json.dumps(revocation_document, separators=(",", ":"))
        revoke = {
            "original_receipt": original,
            "receipt": {
                "epoch": issued["window"]["epoch"],
                "request_id": "b" * 32,
                "profile_id": issued["window"]["binding"]["profile_id"],
                "receipt_sha256": hashlib.sha256(
                    original.encode()
                ).hexdigest(),
                "bytes": len(original.encode()),
            },
        }
        cancelled = await self.client.post(
            f"/v1/admin/subscriptions/{subscription['id']}/provision-failed",
            headers=self.headers,
            json={"reason": "Owned strict refund gate"},
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        base = path.removesuffix("/admission")
        denied = await self.client.post(
            base + "/revocation", headers=self.node_headers, json=revoke
        )
        self.assertEqual(denied.status_code, 409, denied.text)
        settled = await self.client.post(
            base + "/finalize", headers=self.node_headers, json=final
        )
        self.assertEqual(settled.status_code, 200, settled.text)
        responses = await asyncio.gather(
            self.client.post(
                base + "/revocation", headers=self.node_headers, json=revoke
            ),
            self.client.post(
                base + "/revocation", headers=self.node_headers, json=revoke
            ),
        )
        self.assertEqual([r.status_code for r in responses], [200, 200])
        self.assertEqual(responses[0].json(), responses[1].json())
        observed_at = responses[0].json()["data"]["observed_at"]
        self.assertTrue(observed_at.endswith("+00:00"))
        self.assertEqual(datetime.fromisoformat(observed_at).microsecond, 0)
        async with self.connection.uow() as fresh:
            balance = await fresh.execute(
                text(
                    "SELECT balance_rial FROM tbl_wallets WHERE "
                    "customer_id=:id"
                ),
                {"id": subscription["customer_id"]},
            )
            self.assertEqual(balance.scalar_one(), 300000)
            status = await fresh.execute(
                text(
                    "SELECT s.status,r.state,t.state FROM tbl_subscriptions s "
                    "JOIN tbl_provision_requests r ON r.subscription_id=s.id "
                    "JOIN tbl_provision_tasks t ON t.request_id=r.id WHERE "
                    "t.id=:id"
                ),
                {"id": task_id},
            )
            self.assertEqual(
                tuple(status.one()), ("failed", "refunded", "revoked")
            )
            credits = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_wallet_entries WHERE "
                    "reference=:key"
                ),
                {"key": f"provision_refund:{subscription['id']}:0"},
            )
            self.assertEqual(credits.scalar_one(), 1)

    async def test_changed_profile_owner_rejects_first_admission(self):
        _, _, _, issued, submission, path = await self.paid_window()
        original_suffix = self.suffix
        self.suffix += "_other"
        try:
            _, other = await self.paid_subscription()
        finally:
            self.suffix = original_suffix
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    text(
                        "UPDATE tbl_profiles SET "
                        "subscription_id=:subscription "
                        "WHERE id=:profile"
                    ),
                    {
                        "subscription": other["id"],
                        "profile": issued["window"]["binding"]["profile_id"],
                    },
                )
        response = await self.client.post(
            path, headers=self.node_headers, json=submission
        )
        self.assertEqual(response.status_code, 409, response.text)
        async with self.connection.uow() as fresh:
            admissions = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_managed_admissions WHERE "
                    "window_id=:id"
                ),
                {"id": issued["id"]},
            )
            self.assertEqual(admissions.scalar_one(), 0)

    async def paid_window(self):
        subscription, node, expected, body, path, _ = await self.setup_closed()
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
                    "SELECT t.id,t.request_id FROM tbl_provision_tasks t "
                    "JOIN tbl_provision_requests r ON r.id=t.request_id "
                    "WHERE r.subscription_id=:id"
                ),
                {"id": subscription["id"]},
            )
            task_id, request_id = tuple(task.one())
        body["provision_task_id"] = task_id
        responses = await asyncio.gather(
            self.client.post(path, headers=self.node_headers, json=body),
            self.client.post(path, headers=self.node_headers, json=body),
        )
        self.assertEqual([r.status_code for r in responses], [200, 200])
        self.assertEqual(responses[0].json(), responses[1].json())
        issued = responses[0].json()["data"]
        claim = issued["provision_claim"]
        self.assertEqual(claim["task_id"], task_id)
        startup = await self.closed_receipt_sha(issued["id"])
        document = {
            "receipt_version": 1,
            "state": "historical_strict_window_admission",
            "window": issued["window"],
            "window_sha256": issued["window_sha256"],
            "adapter_revision": expected["adapter_revision"],
            "source_commit": expected["source_commit"],
            "module": "github.com/xtls/xray-core@v1.260327.0",
            "accounting_scope": "decoded_managed_tcp_payload_admission",
            "window_policy_sha256": expected["window_policy_sha256"],
            "startup_receipt_sha256": startup,
            "observed_at": datetime.now(UTC).isoformat(),
            "budget_enforced": True,
            "deadline_enforced": True,
            "historical_only": True,
            "api_authority": False,
        }
        original = json.dumps(document, separators=(",", ":"))
        submission = {
            "claim_token": claim["claim_token"],
            "original_receipt": original,
            "receipt": {
                "epoch": issued["window"]["epoch"],
                "window_id": issued["window"]["window_id"],
                "receipt_sha256": hashlib.sha256(
                    original.encode()
                ).hexdigest(),
                "bytes": len(original.encode()),
            },
        }
        ack_path = (
            f"/v1/nodes/{node['node']['code']}/managed-windows/"
            f"{issued['window']['window_id']}/admission"
        )
        return subscription, task_id, request_id, issued, submission, ack_path

    async def closed_receipt_sha(self, id):
        async with self.connection.uow() as fresh:
            rows = await fresh.execute(
                text(
                    "SELECT e.receipt_sha256 FROM tbl_managed_epoches e "
                    "JOIN tbl_managed_windows w ON w.epoch_id=e.id WHERE "
                    "w.id=:id"
                ),
                {"id": id},
            )
            result = rows.scalar_one()
        return result

    async def test_paid_activation_exact_concurrent_replay_and_wallet_once(
        self,
    ):
        (
            subscription,
            task_id,
            request_id,
            _,
            submission,
            path,
        ) = await self.paid_window()
        async with self.connection.uow() as fresh:
            before = await fresh.execute(
                text(
                    "SELECT status,activated_at FROM tbl_subscriptions WHERE "
                    "id=:id"
                ),
                {"id": subscription["id"]},
            )
            self.assertEqual(tuple(before.one()), ("pending_provision", None))
        responses = await asyncio.gather(
            self.client.post(path, headers=self.node_headers, json=submission),
            self.client.post(path, headers=self.node_headers, json=submission),
        )
        self.assertEqual([r.status_code for r in responses], [200, 200])
        self.assertEqual(responses[0].json(), responses[1].json())
        async with self.connection.uow() as fresh:
            rows = await fresh.execute(
                text(
                    "SELECT "
                    "s.status,s.activated_at,r.state,t.state,"
                    "p.applied_generation "
                    "FROM tbl_subscriptions s JOIN tbl_provision_requests r "
                    "ON r.subscription_id=s.id "
                    "JOIN tbl_provision_tasks t ON t.request_id=r.id JOIN "
                    "tbl_profiles p ON p.id=t.profile_id "
                    "WHERE s.id=:id"
                ),
                {"id": subscription["id"]},
            )
            status, activated, request_state, task_state, generation = tuple(
                rows.one()
            )
            self.assertEqual(
                (status, request_state, task_state, generation),
                ("active", "active", "applied", 0),
            )
            self.assertIsNotNone(activated)
            count = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_managed_admissions WHERE "
                    "provision_task_id=:id"
                ),
                {"id": task_id},
            )
            self.assertEqual(count.scalar_one(), 1)
            balance = await fresh.execute(
                text(
                    "SELECT balance_rial FROM tbl_wallets WHERE "
                    "customer_id=:id"
                ),
                {"id": subscription["customer_id"]},
            )
            self.assertEqual(balance.scalar_one(), 200000)
            notices = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_notifications WHERE "
                    "event_key=:key"
                ),
                {"key": f"activation:{request_id}"},
            )
            self.assertEqual(notices.scalar_one(), 1)

    async def test_cancelled_order_retains_reservation_and_rejects_admission(
        self,
    ):
        subscription, _, _, issued, submission, path = await self.paid_window()
        cancelled = await self.client.post(
            f"/v1/admin/subscriptions/{subscription['id']}/provision-failed",
            headers=self.headers,
            json={"reason": "Owned cancelled admission test"},
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        response = await self.client.post(
            path, headers=self.node_headers, json=submission
        )
        self.assertEqual(response.status_code, 409, response.text)
        async with self.connection.uow() as fresh:
            count = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_managed_admissions WHERE "
                    "window_id=:id"
                ),
                {"id": issued["id"]},
            )
            self.assertEqual(count.scalar_one(), 0)
            grant = await fresh.execute(
                text(
                    "SELECT is_closed,allocated_bytes FROM tbl_usage_grants "
                    "WHERE id=:id"
                ),
                {"id": issued["window"]["grant_id"]},
            )
            self.assertEqual(tuple(grant.one()), (0, 1024))
            claim = await fresh.execute(
                text(
                    "SELECT encrypted_provision_claim IS NOT NULL FROM "
                    "tbl_managed_windows WHERE id=:id"
                ),
                {"id": issued["id"]},
            )
            self.assertEqual(claim.scalar_one(), 1)
