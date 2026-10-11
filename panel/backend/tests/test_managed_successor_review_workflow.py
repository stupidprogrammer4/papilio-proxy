"""Native successor replay and paid attribution with external receipts."""

import asyncio
import json

from papilio.infra.db.transaction import transaction
from sqlalchemy import delete, insert, select, text
from sqlmodel import col

from src.modules.network.managed_runtime.domain.models import (
    ManagedAdmissionModel,
)
from src.modules.network.managed_runtime.infra.tables import (
    ManagedAdmissionTable,
)
from tests import test_managed_paid_admission_workflow as paid_reporter
from tests import test_managed_successors_workflow as successor_reporter


class ManagedSuccessorReviewWorkflowTest(
    successor_reporter.ManagedSuccessorWorkflowFixture
):
    async def test_immutable_replays_survive_removed_and_reduced_policies(
        self,
    ):
        (
            subscription,
            node,
            first,
            expected,
            initial,
            initial_path,
        ) = await self.setup_window()
        settled, _ = await self.finalize_window(node, first, expected)
        self.enable_successors()
        path = self.window_path(node, first) + "/successor"
        request = {
            "request_key": "successor_review_replay_" + self.suffix,
            "requested_bytes": 256,
            "acceptance": settled["acceptance"],
        }
        issued = await self.client.post(
            path, headers=self.node_headers, json=request
        )
        self.assertEqual(issued.status_code, 200, issued.text)
        self.assertNotIn("provision_claim", issued.json()["data"])
        initial_replay = await self.client.post(
            initial_path, headers=self.node_headers, json=initial
        )
        self.assertEqual(initial_replay.status_code, 200, initial_replay.text)
        self.assertEqual(initial_replay.json()["data"], first)
        before = await self.accounting(subscription["id"])
        financial_before = await self.financial_count()
        policy, runtime = (
            self.settings.managed_adapter,
            self.settings.core_runtime,
        )
        assert policy is not None and runtime is not None
        try:
            self.settings.managed_adapter = None
            self.settings.core_runtime = None
            replay = await self.client.post(
                path, headers=self.node_headers, json=request
            )
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertEqual(replay.json(), issued.json())
            new_request = {
                **request,
                "request_key": "successor_review_new_" + self.suffix,
            }
            denied = await self.client.post(
                path, headers=self.node_headers, json=new_request
            )
            self.assertEqual(denied.status_code, 409, denied.text)
            self.assertEqual(await self.accounting(subscription["id"]), before)
            self.assertEqual(await self.financial_count(), financial_before)
            self.settings.managed_adapter = policy
            self.settings.core_runtime = runtime
            self.enable_successors(profile_windows=2, epoch_windows=2)
            self.settings.core_runtime = runtime.model_copy(
                update={"max_profiles": 1, "max_configurations": 1}
            )
            reduced_replay = await self.client.post(
                path, headers=self.node_headers, json=request
            )
            self.assertEqual(
                reduced_replay.status_code, 200, reduced_replay.text
            )
            self.assertEqual(reduced_replay.json(), issued.json())
            reduced_denied = await self.client.post(
                path, headers=self.node_headers, json=new_request
            )
            self.assertEqual(
                reduced_denied.status_code, 409, reduced_denied.text
            )
            self.assertEqual(await self.accounting(subscription["id"]), before)
            self.assertEqual(await self.financial_count(), financial_before)
        finally:
            self.settings.managed_adapter = policy
            self.settings.core_runtime = runtime


class ManagedPaidSuccessorReviewFixture(
    successor_reporter.ManagedSuccessorWorkflowFixture
):
    paid_managed_fixture = True
    paid_window = paid_reporter.ManagedPaidAdmissionWorkflowTest.paid_window
    closed_receipt_sha = (
        paid_reporter.ManagedPaidAdmissionWorkflowTest.closed_receipt_sha
    )

    async def paid_effects(self, subscription_id, task_id, request_id):
        async with self.connection.uow() as fresh:
            result = await fresh.execute(
                text(
                    "SELECT s.status,s.activated_at,r.state,t.state,"
                    "t.attempts,"
                    "(SELECT balance_rial FROM tbl_wallets "
                    "WHERE customer_id=s.customer_id),"
                    "(SELECT COUNT(*) FROM tbl_wallet_entries e "
                    "JOIN tbl_wallets w ON w.id=e.wallet_id "
                    "WHERE w.customer_id=s.customer_id),"
                    "(SELECT COUNT(*) FROM tbl_notifications "
                    "WHERE event_key=:notice),"
                    "(SELECT COUNT(*) FROM tbl_provision_tasks "
                    "WHERE request_id=r.id),"
                    "(SELECT COUNT(*) FROM tbl_managed_admissions "
                    "WHERE provision_task_id=t.id) "
                    "FROM tbl_subscriptions s JOIN tbl_provision_requests r "
                    "ON r.id=:request JOIN tbl_provision_tasks t "
                    "ON t.id=:task WHERE s.id=:subscription"
                ),
                {
                    "subscription": subscription_id,
                    "task": task_id,
                    "request": request_id,
                    "notice": f"activation:{request_id}",
                },
            )
            return tuple(result.one())


class ManagedPaidSuccessorReviewWorkflowTest(
    ManagedPaidSuccessorReviewFixture
):
    async def test_paid_root_required_and_private_attribution_preserved(self):
        (
            subscription,
            task_id,
            request_id,
            first,
            admission,
            admission_path,
        ) = await self.paid_window()
        accepted = await self.client.post(
            admission_path, headers=self.node_headers, json=admission
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        expected = json.loads(admission["original_receipt"])
        final_body = await asyncio.to_thread(
            self.final_submission, first, expected, 120, 30
        )
        base = admission_path.removesuffix("/admission")
        finalized = await self.client.post(
            base + "/finalize", headers=self.node_headers, json=final_body
        )
        self.assertEqual(finalized.status_code, 200, finalized.text)
        self.enable_successors()
        before = await self.paid_effects(
            subscription["id"], task_id, request_id
        )
        self.assertEqual(before[0], "active")
        self.assertEqual(before[7:], (1, 1, 1))
        request = {
            "request_key": "successor_paid_review_" + self.suffix,
            "requested_bytes": 256,
            "acceptance": finalized.json()["data"]["acceptance"],
        }
        # Remove only persisted original admission evidence, then restore it
        # exactly: live paid state alone must not authorize continuation.
        async with self.connection.uow() as fresh:
            async with transaction(fresh):
                result = await fresh.execute(
                    select(ManagedAdmissionTable).where(
                        col(ManagedAdmissionTable.window_id) == first["id"]
                    )
                )
                original = ManagedAdmissionModel.model_validate(
                    result.scalar_one().model_dump()
                )
                await fresh.execute(
                    delete(ManagedAdmissionTable).where(
                        col(ManagedAdmissionTable.id) == original.id
                    )
                )
        try:
            denied = await self.client.post(
                base + "/successor", headers=self.node_headers, json=request
            )
            self.assertEqual(denied.status_code, 409, denied.text)
            self.assertIn("managed_successor_paid_root_invalid", denied.text)
            self.assertEqual(
                await self.accounting(subscription["id"]), (150, 0, 1, 1, 150)
            )
        finally:
            async with self.connection.uow() as fresh:
                async with transaction(fresh):
                    await fresh.execute(
                        insert(ManagedAdmissionTable).values(original.to_row())
                    )
        self.assertEqual(
            await self.paid_effects(subscription["id"], task_id, request_id),
            before,
        )
        response = await self.client.post(
            base + "/successor", headers=self.node_headers, json=request
        )
        self.assertEqual(response.status_code, 200, response.text)
        successor = response.json()["data"]
        self.assertNotIn("provision_claim", successor)
        self.assertEqual(successor["window"]["baseline_upload_bytes"], 120)
        self.assertEqual(successor["window"]["baseline_download_bytes"], 30)
        async with self.connection.uow() as fresh:
            attribution = await fresh.execute(
                text(
                    "SELECT child.provision_task_id=parent.provision_task_id,"
                    "child.encrypted_provision_claim="
                    "parent.encrypted_provision_claim,"
                    "child.encrypted_provision_claim IS NOT NULL "
                    "FROM tbl_managed_windows child "
                    "JOIN tbl_managed_windows parent ON parent.id=:parent "
                    "WHERE child.id=:child"
                ),
                {"parent": first["id"], "child": successor["id"]},
            )
            self.assertEqual(tuple(attribution.one()), (1, 1, 1))
        self.assertEqual(
            await self.accounting(subscription["id"]), (150, 256, 2, 1, 150)
        )
        self.assertEqual(
            await self.paid_effects(subscription["id"], task_id, request_id),
            before,
        )
