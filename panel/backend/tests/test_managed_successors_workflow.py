"""Native continuation workflows with constructed external final receipts."""

import asyncio
import hashlib
import json
from uuid import uuid4

from sqlalchemy import text

from src.modules.network.managed_runtime.domain.successors import (
    ManagedSuccessorLimits,
    ManagedSuccessorPolicy,
)
from tests.test_ip_limit_workflow import IpLimitWorkflowFixture
from tests.test_managed_finality_workflow import (
    ManagedFinalityWorkflowTest,
)
from tests.test_managed_windows_workflow import ManagedWindowWorkflowFixture


class ManagedSuccessorWorkflowFixture(
    ManagedWindowWorkflowFixture, IpLimitWorkflowFixture
):
    def enable_successors(self, *, profile_windows=4, epoch_windows=8):
        policy = self.settings.managed_adapter
        assert policy is not None
        self.settings.managed_adapter = policy.model_copy(
            update={
                "successor_policy": ManagedSuccessorPolicy(
                    mode="bounded",
                    limits=ManagedSuccessorLimits(
                        max_windows_per_profile_epoch=profile_windows,
                        max_windows_per_epoch=epoch_windows,
                        max_epoch_seconds=300,
                        max_requested_bytes=1024,
                    ),
                )
            }
        )

    @staticmethod
    def final_submission(issued, expected, upload, download):
        initial = ManagedFinalityWorkflowTest.frozen_submission(
            issued, expected
        )
        snapshot = json.loads(initial["original_receipt"])
        wire = issued["window"]
        snapshot["barrier_id"] = uuid4().hex
        snapshot["profiles"][0]["upload_bytes"] = (
            wire["baseline_upload_bytes"] + upload
        )
        snapshot["profiles"][0]["download_bytes"] = (
            wire["baseline_download_bytes"] + download
        )
        snapshot["enforcement"][0]["admitted_bytes"] = upload + download
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

    def window_path(self, node, issued):
        return (
            f"/v1/nodes/{node['node']['code']}/managed-windows/"
            f"{issued['window']['window_id']}"
        )

    async def finalize_window(
        self, node, issued, expected, *, upload=120, download=30
    ):
        body = await asyncio.to_thread(
            self.final_submission, issued, expected, upload, download
        )
        response = await self.client.post(
            self.window_path(node, issued) + "/finalize",
            headers=self.node_headers,
            json=body,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"], body

    async def accounting(self, subscription_id):
        async with self.connection.uow() as fresh:
            result = await fresh.execute(
                text(
                    "SELECT s.used_bytes,"
                    "(SELECT COALESCE(SUM(g.allocated_bytes),0) "
                    "FROM tbl_usage_grants g WHERE g.subscription_id=s.id "
                    "AND g.is_closed=0),"
                    "(SELECT COUNT(*) FROM tbl_managed_windows w "
                    "WHERE w.subscription_id=s.id),"
                    "(SELECT COUNT(*) FROM tbl_usage_events e "
                    "WHERE e.subscription_id=s.id),"
                    "(SELECT COALESCE(SUM(e.delta_bytes),0) "
                    "FROM tbl_usage_events e WHERE e.subscription_id=s.id) "
                    "FROM tbl_subscriptions s WHERE s.id=:id"
                ),
                {"id": subscription_id},
            )
            return tuple(result.one())

    async def financial_count(self):
        async with self.connection.uow() as fresh:
            result = await fresh.execute(
                text("SELECT COUNT(*) FROM tbl_wallet_entries")
            )
            return result.scalar_one()


class ManagedSuccessorsWorkflowTest(ManagedSuccessorWorkflowFixture):
    async def test_other_node_reservation_bounds_successor_quota(self):
        self.fixture_quota = 1024
        subscription, node, first, expected, _, _ = await self.setup_window()
        async with self.connection.uow() as fresh:
            plan_quota = await fresh.execute(
                text("SELECT quota_bytes FROM tbl_plans WHERE id=:id"),
                {"id": subscription["plan_id"]},
            )
            self.assertEqual(plan_quota.scalar_one(), self.fixture_quota)
        settled, _ = await self.finalize_window(node, first, expected)
        self.enable_successors()
        other = await self.register_assignment(
            subscription["id"], "successor_quota_other"
        )
        async with self.connection.uow() as fresh:
            profiles = await fresh.execute(
                text("SELECT id FROM tbl_profiles WHERE configuration_id=:id"),
                {"id": other["configuration_id"]},
            )
            profile_id = profiles.scalar_one()
        reserved = await self.client.post(
            f"/v1/nodes/{other['node']['code']}/usage/grants",
            headers={"X-Papilio-Node-Key": other["agent_key"]},
            json={
                "profile_id": profile_id,
                "generation": 0,
                "request_key": "successor_other_reservation_" + self.suffix,
                "requested_bytes": 600,
            },
        )
        self.assertEqual(reserved.status_code, 200, reserved.text)
        request = {
            "request_key": "successor_shared_quota_" + self.suffix,
            "requested_bytes": 300,
            "acceptance": settled["acceptance"],
        }
        denied = await self.client.post(
            self.window_path(node, first) + "/successor",
            headers=self.node_headers,
            json=request,
        )
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertIn("usage_quota_unavailable", denied.text)
        self.assertEqual(
            await self.accounting(subscription["id"]), (150, 600, 1, 1, 150)
        )

    async def test_disabled_then_three_windows_exact_replay_and_accounting(
        self,
    ):
        subscription, node, first, expected, _, _ = await self.setup_window()
        financial_before = await self.financial_count()
        settled, original = await self.finalize_window(node, first, expected)
        first_path = self.window_path(node, first) + "/successor"
        request = {
            "request_key": "successor_first_" + self.suffix,
            "requested_bytes": 256,
            "acceptance": settled["acceptance"],
        }
        disabled = await self.client.post(
            first_path, headers=self.node_headers, json=request
        )
        self.assertEqual(disabled.status_code, 409, disabled.text)
        self.enable_successors()
        responses = await asyncio.gather(
            self.client.post(
                first_path, headers=self.node_headers, json=request
            ),
            self.client.post(
                first_path, headers=self.node_headers, json=request
            ),
        )
        self.assertEqual([row.status_code for row in responses], [200, 200])
        second = responses[0].json()["data"]
        self.assertEqual(second, responses[1].json()["data"])
        self.assertIsNone(second.get("provision_claim"))
        self.assertEqual(second["window"]["baseline_upload_bytes"], 120)
        self.assertEqual(second["window"]["baseline_download_bytes"], 30)
        self.assertEqual(
            second["window"]["predecessor"], settled["acceptance"]
        )
        reused = await self.client.post(
            first_path,
            headers=self.node_headers,
            json={**request, "requested_bytes": 257},
        )
        self.assertEqual(reused.status_code, 409, reused.text)
        sibling = await self.client.post(
            first_path,
            headers=self.node_headers,
            json={**request, "request_key": "other_successor_" + self.suffix},
        )
        self.assertEqual(sibling.status_code, 409, sibling.text)
        settled_second, _ = await self.finalize_window(
            node, second, expected, upload=90, download=60
        )
        stale = await self.client.post(
            first_path,
            headers=self.node_headers,
            json={
                **request,
                "request_key": "stale_predecessor_" + self.suffix,
            },
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        third_request = {
            "request_key": "successor_second_" + self.suffix,
            "requested_bytes": 256,
            "acceptance": settled_second["acceptance"],
        }
        third_response = await self.client.post(
            self.window_path(node, second) + "/successor",
            headers=self.node_headers,
            json=third_request,
        )
        self.assertEqual(third_response.status_code, 200, third_response.text)
        third = third_response.json()["data"]
        self.assertEqual(third["window"]["baseline_upload_bytes"], 210)
        self.assertEqual(third["window"]["baseline_download_bytes"], 90)
        replay_final = await self.client.post(
            self.window_path(node, first) + "/finalize",
            headers=self.node_headers,
            json=original,
        )
        self.assertEqual(replay_final.status_code, 200, replay_final.text)
        self.assertEqual(replay_final.json()["data"], settled)
        replay_first = await self.client.post(
            first_path, headers=self.node_headers, json=request
        )
        self.assertEqual(replay_first.status_code, 200, replay_first.text)
        self.assertEqual(replay_first.json()["data"], second)
        self.assertEqual(
            await self.accounting(subscription["id"]), (300, 256, 3, 2, 300)
        )
        self.assertEqual(await self.financial_count(), financial_before)

    async def test_wrong_acceptance_and_finite_profile_capacity(self):
        subscription, node, first, expected, _, _ = await self.setup_window()
        settled, _ = await self.finalize_window(node, first, expected)
        self.enable_successors(profile_windows=2, epoch_windows=4)
        path = self.window_path(node, first) + "/successor"
        request = {
            "request_key": "bounded_successor_" + self.suffix,
            "requested_bytes": 256,
            "acceptance": settled["acceptance"],
        }
        invalid = await self.client.post(
            path,
            headers=self.node_headers,
            json={
                **request,
                "acceptance": {
                    **request["acceptance"],
                    "snapshot_sha256": "0" * 64,
                },
            },
        )
        self.assertEqual(invalid.status_code, 409, invalid.text)
        valid = await self.client.post(
            path, headers=self.node_headers, json=request
        )
        self.assertEqual(valid.status_code, 200, valid.text)
        second = valid.json()["data"]
        second_final, _ = await self.finalize_window(
            node, second, expected, upload=90, download=60
        )
        limited = await self.client.post(
            self.window_path(node, second) + "/successor",
            headers=self.node_headers,
            json={
                "request_key": "over_capacity_" + self.suffix,
                "requested_bytes": 256,
                "acceptance": second_final["acceptance"],
            },
        )
        self.assertEqual(limited.status_code, 409, limited.text)
        self.assertEqual(
            await self.accounting(subscription["id"]), (300, 0, 2, 2, 300)
        )
