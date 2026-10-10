"""Native first admission rejects explicitly changed stored credentials."""

import asyncio
from uuid import uuid4

from papilio.infra.db.transaction import transaction
from papilio.security.crypto import encrypt
from sqlalchemy import text

from src.modules.network.configurations.domain.results import (
    ClientCredentials,
)
from tests import test_managed_paid_admission_workflow as paid_reporter
from tests.test_managed_windows_workflow import ManagedWindowWorkflowFixture


class ManagedAdmissionMembershipWorkflowTest(ManagedWindowWorkflowFixture):
    paid_managed_fixture = True
    paid_window = paid_reporter.ManagedPaidAdmissionWorkflowTest.paid_window
    closed_receipt_sha = (
        paid_reporter.ManagedPaidAdmissionWorkflowTest.closed_receipt_sha
    )

    async def test_historical_admission_replay_without_runtime_policy(self):
        _, task_id, _, issued, submission, path = await self.paid_window()
        accepted = await self.client.post(
            path, headers=self.node_headers, json=submission
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.settings.core_runtime = None
        self.settings.managed_adapter = None
        replay = await self.client.post(
            path, headers=self.node_headers, json=submission
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json(), accepted.json())
        async with self.connection.uow() as fresh:
            admission = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_managed_admissions "
                    "WHERE window_id=:id AND provision_task_id=:task"
                ),
                {"id": issued["id"], "task": task_id},
            )
            self.assertEqual(admission.scalar_one(), 1)

    async def test_first_admission_rejects_changed_current_credentials(self):
        (
            subscription,
            task_id,
            _,
            issued,
            submission,
            path,
        ) = await self.paid_window()
        profile_id = issued["window"]["binding"]["profile_id"]
        # Explicit persisted credential-change fault after issued membership;
        # the external reporter receipt remains bound to the original window.
        credentials = ClientCredentials(identity=str(uuid4()))
        ciphertext = await asyncio.to_thread(
            encrypt,
            credentials.model_dump_json(),
            self.settings.configuration_encryption_key,
        )
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    text(
                        "UPDATE tbl_profiles SET encrypted_credentials=:value "
                        "WHERE id=:id"
                    ),
                    {"id": profile_id, "value": ciphertext},
                )
        response = await self.client.post(
            path, headers=self.node_headers, json=submission
        )
        self.assertEqual(response.status_code, 409, response.text)
        async with self.connection.uow() as fresh:
            state = await fresh.execute(
                text(
                    "SELECT s.status,s.activated_at,t.state,"
                    "p.applied_generation FROM tbl_subscriptions s "
                    "JOIN tbl_provision_requests r ON r.subscription_id=s.id "
                    "JOIN tbl_provision_tasks t ON t.request_id=r.id "
                    "JOIN tbl_profiles p ON p.id=t.profile_id "
                    "WHERE s.id=:subscription AND t.id=:task"
                ),
                {"subscription": subscription["id"], "task": task_id},
            )
            self.assertEqual(
                tuple(state.one()), ("pending_provision", None, "leased", None)
            )
            admissions = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_managed_admissions "
                    "WHERE window_id=:id"
                ),
                {"id": issued["id"]},
            )
            self.assertEqual(admissions.scalar_one(), 0)
            grant = await fresh.execute(
                text(
                    "SELECT is_closed,allocated_bytes,upload_bytes,"
                    "download_bytes FROM tbl_usage_grants WHERE id=:id"
                ),
                {"id": issued["window"]["grant_id"]},
            )
            self.assertEqual(tuple(grant.one()), (0, 1024, 0, 0))
            wallet = await fresh.execute(
                text(
                    "SELECT balance_rial FROM tbl_wallets "
                    "WHERE customer_id=:id"
                ),
                {"id": subscription["customer_id"]},
            )
            self.assertEqual(wallet.scalar_one(), 200000)
