"""Native historical admission and current revocation assignment boundaries."""

import hashlib
import json
from datetime import UTC, datetime

from papilio.infra.db.transaction import transaction
from sqlalchemy import text

from tests import test_managed_finality_workflow as final_reporter
from tests import test_managed_paid_admission_workflow as paid_reporter
from tests.test_managed_windows_workflow import ManagedWindowWorkflowFixture


class ManagedPaidLifecycleReviewWorkflowTest(ManagedWindowWorkflowFixture):
    paid_managed_fixture = True
    paid_window = paid_reporter.ManagedPaidAdmissionWorkflowTest.paid_window
    closed_receipt_sha = (
        paid_reporter.ManagedPaidAdmissionWorkflowTest.closed_receipt_sha
    )

    async def effects(self, subscription, task_id):
        async with self.connection.uow() as fresh:
            result = await fresh.execute(
                text(
                    "SELECT s.status,s.activated_at,s.used_bytes,r.state,"
                    "t.state,p.applied_generation,"
                    "(SELECT balance_rial FROM tbl_wallets "
                    "WHERE customer_id=s.customer_id),"
                    "(SELECT COUNT(*) FROM tbl_managed_admissions "
                    "WHERE provision_task_id=t.id),"
                    "(SELECT COUNT(*) FROM tbl_managed_revocations "
                    "WHERE provision_task_id=t.id),"
                    "(SELECT COUNT(*) FROM tbl_wallet_entries "
                    "WHERE reference=:refund) "
                    "FROM tbl_subscriptions s JOIN tbl_provision_requests r "
                    "ON r.subscription_id=s.id JOIN tbl_provision_tasks t "
                    "ON t.request_id=r.id JOIN tbl_profiles p "
                    "ON p.id=t.profile_id WHERE s.id=:id AND t.id=:task"
                ),
                {
                    "id": subscription["id"],
                    "task": task_id,
                    "refund": f"provision_refund:{subscription['id']}:0",
                },
            )
            effects = tuple(result.one())
        return effects

    async def test_historical_admission_ignores_new_members_and_lower_capacity(
        self,
    ):
        (
            subscription,
            task_id,
            _,
            issued,
            submission,
            path,
        ) = await self.paid_window()
        accepted = await self.client.post(
            path, headers=self.node_headers, json=submission
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        before = await self.effects(subscription, task_id)
        original_suffix = self.suffix
        self.suffix += "_second"
        try:
            _, other = await self.paid_subscription()
        finally:
            self.suffix = original_suffix
        configuration_id = issued["window"]["binding"]["configuration_id"]
        await self.post(
            f"/v1/admin/network/configurations/{configuration_id}/profiles",
            {"subscription_id": other["id"]},
        )
        async with self.connection.uow() as fresh:
            profiles = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_profiles WHERE "
                    "configuration_id=:id"
                ),
                {"id": configuration_id},
            )
            self.assertEqual(profiles.scalar_one(), 2)
        runtime = self.settings.core_runtime
        assert runtime is not None
        runtime.max_profiles = 1
        replay = await self.client.post(
            path, headers=self.node_headers, json=submission
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json(), accepted.json())
        self.assertEqual(await self.effects(subscription, task_id), before)

    async def test_first_revocation_rejects_moved_core_then_recovers(self):
        (
            subscription,
            task_id,
            _,
            issued,
            admission,
            path,
        ) = await self.paid_window()
        expected = json.loads(admission["original_receipt"])
        final = final_reporter.ManagedFinalityWorkflowTest.frozen_submission(
            issued, expected
        )
        wire = issued["window"]
        request_id = "b" * 32
        document = {
            "receipt_version": 1,
            "state": "historical_epoch_profile_revoked",
            "request": {
                "epoch": wire["epoch"],
                "request_id": request_id,
                "barrier_id": final["receipt"]["barrier_id"],
                "window_id": wire["window_id"],
                "binding": wire["binding"],
            },
            "window": wire,
            "installation": wire["installation"],
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
        original = json.dumps(document, separators=(",", ":"))
        submission = {
            "original_receipt": original,
            "receipt": {
                "epoch": wire["epoch"],
                "request_id": request_id,
                "profile_id": wire["binding"]["profile_id"],
                "receipt_sha256": hashlib.sha256(
                    original.encode()
                ).hexdigest(),
                "bytes": len(original.encode()),
            },
        }
        cancelled = await self.client.post(
            f"/v1/admin/subscriptions/{subscription['id']}/provision-failed",
            headers=self.headers,
            json={"reason": "Owned moved-core revocation regression"},
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        base = path.removesuffix("/admission")
        settled = await self.client.post(
            base + "/finalize", headers=self.node_headers, json=final
        )
        self.assertEqual(settled.status_code, 200, settled.text)
        configuration_id = wire["binding"]["configuration_id"]
        async with self.connection.uow() as fresh:
            assignment = await fresh.execute(
                text(
                    "SELECT node_id,core_id FROM tbl_configurations "
                    "WHERE id=:id"
                ),
                {"id": configuration_id},
            )
            node_id, original_core = tuple(assignment.one())
        other_core = await self.post(
            f"/v1/admin/network/nodes/{node_id}/cores",
            {
                "code": "moved_" + self.suffix,
                "label": "Owned alternate native core",
                "kind": "xray",
            },
        )
        async with self.connection.uow() as unit:
            async with transaction(unit):
                # Explicit storage movement models a current assignment drift;
                # its old historical receipt must not revoke the new core.
                await unit.execute(
                    text(
                        "UPDATE tbl_configurations SET core_id=:core "
                        "WHERE id=:id"
                    ),
                    {"core": other_core["id"], "id": configuration_id},
                )
        before = await self.effects(subscription, task_id)
        denied = await self.client.post(
            base + "/revocation", headers=self.node_headers, json=submission
        )
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertEqual(await self.effects(subscription, task_id), before)
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    text(
                        "UPDATE tbl_configurations SET core_id=:core "
                        "WHERE id=:id"
                    ),
                    {"core": original_core, "id": configuration_id},
                )
        recovered = await self.client.post(
            base + "/revocation", headers=self.node_headers, json=submission
        )
        self.assertEqual(recovered.status_code, 200, recovered.text)
        after = await self.effects(subscription, task_id)
        self.assertEqual(after[0], "failed")
        self.assertEqual(after[3:5], ("refunded", "revoked"))
        self.assertEqual(after[6:], (300000, 0, 1, 1))
