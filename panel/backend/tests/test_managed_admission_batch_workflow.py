"""Real API acceptance for atomic paid managed-window admission batches."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
from papilio.infra.db.transaction import transaction
from sqlalchemy import text

from tests.test_managed_windows_workflow import ManagedWindowWorkflowFixture


class ManagedAdmissionBatchWorkflowTest(ManagedWindowWorkflowFixture):
    async def test_two_paid_profiles_accept_atomically_and_replay(self):
        self.add_second_managed_profile = True
        self.second_paid_managed_profile = True
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
            update={"window_mode": "reserved", "paid_mode": "strict_admission"}
        )
        configuration_id = expected["profiles"][0]["binding"][
            "configuration_id"
        ]
        async with self.connection.uow() as fresh:
            profile_rows = await fresh.execute(
                text(
                    "SELECT p.id,p.subscription_id,r.id FROM tbl_profiles p "
                    "JOIN tbl_provision_requests r "
                    "ON r.subscription_id=p.subscription_id "
                    "WHERE p.configuration_id=:configuration "
                    "ORDER BY p.id"
                ),
                {"configuration": configuration_id},
            )
            profiles = [tuple(row) for row in profile_rows]
        self.assertEqual(len(profiles), 2)
        second_subscription_id = next(
            item[1] for item in profiles if item[1] != subscription["id"]
        )
        async with self.connection.uow() as fresh:
            task_rows = await fresh.execute(
                text(
                    "SELECT profile_id,id FROM tbl_provision_tasks "
                    "WHERE request_id IN (SELECT id FROM "
                    "tbl_provision_requests WHERE subscription_id IN "
                    "(:first,:second)) ORDER BY profile_id"
                ),
                {
                    "first": subscription["id"],
                    "second": second_subscription_id,
                },
            )
            tasks = {profile_id: task_id for profile_id, task_id in task_rows}
        self.assertEqual(set(tasks), {item[0] for item in profiles})
        issue = {
            "batch_request_key": "issue_admission_" + self.suffix,
            "windows": [
                {
                    **first,
                    "profile_id": profile_id,
                    "request_key": f"window_{profile_id}_{self.suffix}",
                    "provision_task_id": task_id,
                }
                for profile_id, task_id in sorted(tasks.items())
            ],
        }
        issued = await self.client.post(
            path + "/batch", headers=self.node_headers, json=issue
        )
        self.assertEqual(issued.status_code, 200, issued.text)
        windows = issued.json()["data"]["windows"]
        async with self.connection.uow() as fresh:
            validity_rows = await fresh.execute(
                text(
                    "SELECT w.valid_until,t.claim_until FROM "
                    "tbl_managed_windows w JOIN tbl_provision_tasks t "
                    "ON t.id=w.provision_task_id "
                    "WHERE w.id IN (:first,:second)"
                ),
                {
                    "first": windows[0]["window"]["id"],
                    "second": windows[1]["window"]["id"],
                },
            )
            validities = list(validity_rows)
            startup_rows = await fresh.execute(
                text(
                    "SELECT e.receipt_sha256 FROM tbl_managed_epoches e "
                    "JOIN tbl_managed_windows w ON w.epoch_id=e.id "
                    "WHERE w.id=:id"
                ),
                {"id": windows[0]["window"]["id"]},
            )
            startup_sha256 = startup_rows.scalar_one()
        minimum_validity = datetime.now(UTC).replace(tzinfo=None) + timedelta(
            seconds=20
        )
        self.assertTrue(
            all(
                valid_until > minimum_validity
                and claim_until > minimum_validity
                for valid_until, claim_until in validities
            ),
            f"Batch test fixture returned short-lived claims: {validities}",
        )
        submissions = [
            {
                "window_id": item["window"]["window"]["window_id"],
                "submission": self._submission(
                    item["window"], expected, startup_sha256
                ),
            }
            for item in windows
        ]
        route = (
            f"/v1/nodes/{node['node']['code']}/managed-windows/admission/batch"
        )
        body = {
            "batch_request_key": "admission_batch_" + self.suffix,
            "windows": submissions,
        }
        async with self.connection.uow() as setup:
            async with transaction(setup):
                await setup.execute(
                    text(
                        "CREATE TRIGGER fail_managed_batch_task_update "
                        "BEFORE UPDATE ON tbl_provision_tasks FOR EACH ROW "
                        "SIGNAL SQLSTATE '45000' "
                        "SET MESSAGE_TEXT='controlled batch rollback'"
                    )
                )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=self.app, raise_app_exceptions=False
            ),
            base_url="https://admin.example.com",
        ) as fault_client:
            rejected = await fault_client.post(
                route, headers=self.node_headers, json=body
            )
        self.assertEqual(rejected.status_code, 500, rejected.text)
        async with self.connection.uow() as restore:
            async with transaction(restore):
                await restore.execute(
                    text("DROP TRIGGER fail_managed_batch_task_update")
                )
        async with self.connection.uow() as fresh:
            admission_count = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_managed_admissions "
                    "WHERE window_id IN (:first,:second)"
                ),
                {
                    "first": windows[0]["window"]["id"],
                    "second": windows[1]["window"]["id"],
                },
            )
            operation_count = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_managed_operation_batches "
                    "WHERE request_key=:request_key"
                ),
                {"request_key": body["batch_request_key"]},
            )
            self.assertEqual(admission_count.scalar_one(), 0)
            self.assertEqual(operation_count.scalar_one(), 0)
        response = await self.client.post(
            route, headers=self.node_headers, json=body
        )
        self.assertEqual(response.status_code, 200, response.text)
        observed_at = response.json()["data"]["windows"][0]["result"][
            "observed_at"
        ]
        self.assertRegex(observed_at, r"(?:Z|\+00:00)$")
        self.assertEqual(datetime.fromisoformat(observed_at).microsecond, 0)
        replay, concurrent = await asyncio.gather(
            self.client.post(route, headers=self.node_headers, json=body),
            self.client.post(route, headers=self.node_headers, json=body),
        )
        self.assertEqual(
            [replay.status_code, concurrent.status_code], [200, 200]
        )
        self.assertEqual(replay.json()["data"], response.json()["data"])
        self.assertEqual(concurrent.json()["data"], response.json()["data"])
        async with self.connection.uow() as fresh:
            rows = await fresh.execute(
                text(
                    "SELECT s.id,s.status,r.state,t.state,"
                    "p.applied_generation "
                    "FROM tbl_subscriptions s JOIN tbl_provision_requests r "
                    "ON r.subscription_id=s.id JOIN tbl_provision_tasks t "
                    "ON t.request_id=r.id JOIN tbl_profiles p "
                    "ON p.id=t.profile_id WHERE s.id IN (:first,:second) "
                    "ORDER BY s.id"
                ),
                {
                    "first": subscription["id"],
                    "second": second_subscription_id,
                },
            )
            self.assertEqual(
                [tuple(row)[1:] for row in rows],
                [("active", "active", "applied", 0)] * 2,
            )
            count = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_managed_admissions WHERE "
                    "provision_task_id IN (:first,:second)"
                ),
                {
                    "first": tasks[profiles[0][0]],
                    "second": tasks[profiles[1][0]],
                },
            )
            self.assertEqual(count.scalar_one(), 2)
            links = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_subscription_links "
                    "WHERE subscription_id IN (:first,:second)"
                ),
                {
                    "first": subscription["id"],
                    "second": second_subscription_id,
                },
            )
            self.assertEqual(links.scalar_one(), 2)
            notifications = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_notifications "
                    "WHERE event_key IN ("
                    "SELECT CONCAT('activation:',id) "
                    "FROM tbl_provision_requests "
                    "WHERE subscription_id IN (:first,:second))"
                ),
                {
                    "first": subscription["id"],
                    "second": second_subscription_id,
                },
            )
            self.assertEqual(notifications.scalar_one(), 2)

    @staticmethod
    def _submission(issued, expected, startup_sha256):
        claim = issued["provision_claim"]
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
            "startup_receipt_sha256": startup_sha256,
            "observed_at": datetime.now(UTC).isoformat(),
            "budget_enforced": True,
            "deadline_enforced": True,
            "historical_only": True,
            "api_authority": False,
        }
        original = json.dumps(document, separators=(",", ":"))
        return {
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
