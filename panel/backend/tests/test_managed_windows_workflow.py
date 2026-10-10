"""Native reservations with a constructed CLOSED reporter."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime

from papilio.infra.db.transaction import transaction
from sqlalchemy import text

from tests.test_ip_limit_workflow import IpLimitWorkflowFixture
from tests.test_managed_installation_workflow import (
    ManagedInstallationWorkflowFixture,
)


class ManagedWindowWorkflowFixture(ManagedInstallationWorkflowFixture):
    async def paid_subscription(self, auto_renew=False):
        customer, subscription = await super().paid_subscription(auto_renew)
        quota = getattr(self, "fixture_quota", None)
        if quota is not None:
            async with self.connection.uow() as unit:
                async with transaction(unit):
                    await unit.execute(
                        text(
                            "UPDATE tbl_subscriptions SET quota_bytes=:quota "
                            "WHERE id=:id"
                        ),
                        {"quota": quota, "id": subscription["id"]},
                    )
            subscription["quota_bytes"] = quota
        return customer, subscription

    async def setup_closed(self):
        self.settings.usage.policy.mode = "reserved"
        _, subscription, node, configuration = await self.setup_installation()
        issued = await self.issue()
        self.assertEqual(issued.status_code, 200, issued.text)
        installation_id = issued.json()["data"]["id"]
        claimed = await self.client.post(
            f"{self.node_path}/{installation_id}/claim",
            headers=self.node_headers,
        )
        self.assertEqual(claimed.status_code, 200, claimed.text)
        claim = claimed.json()["data"]
        expected = claim["expectation"]
        document = {
            "state": "isolated_closed_startup_observation",
            "epoch": "e" * 32,
            "installation": expected["installation"],
            "adapter_revision": expected["adapter_revision"],
            "source_commit": expected["source_commit"],
            "module": "github.com/xtls/xray-core@v1.260327.0",
            "accounting_scope": "decoded_managed_tcp_payload_admission",
            "accounting_mode": "window_component",
            "enforcement_mode": "strict_decoded",
            "enforcement_sha256": expected["enforcement_sha256"],
            "window_policy_sha256": expected["window_policy_sha256"],
            "profiles": expected["profiles"],
            "api_authority": False,
            "budget_enforced": False,
            "deadline_enforced": False,
            "historical_only": True,
            "observed_at": datetime.now(UTC).isoformat(),
        }
        original = json.dumps(document, separators=(",", ":"))
        accepted = await self.client.post(
            f"{self.node_path}/{installation_id}/acknowledge",
            headers=self.node_headers,
            json={
                "claim_token": claim["claim_token"],
                "original_receipt": original,
                "receipt": {
                    "epoch": document["epoch"],
                    "receipt_sha256": hashlib.sha256(
                        original.encode()
                    ).hexdigest(),
                    "bytes": len(original.encode()),
                },
            },
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        profile_id = expected["profiles"][0]["binding"]["profile_id"]
        body = {
            "profile_id": profile_id,
            "generation": 0,
            "process_epoch": document["epoch"],
            "request_key": "initial_window_" + self.suffix,
            "requested_bytes": 1024,
        }
        path = f"{self.node_path}/{installation_id}/windows"
        return subscription, node, expected, body, path, configuration

    async def setup_window(self):
        subscription, node, expected, body, path, _ = await self.setup_closed()
        policy = self.settings.managed_adapter
        assert policy is not None
        self.settings.managed_adapter = policy.model_copy(
            update={"window_mode": "reserved"}
        )
        response = await self.client.post(
            path, headers=self.node_headers, json=body
        )
        self.assertEqual(response.status_code, 200, response.text)
        return (
            subscription,
            node,
            response.json()["data"],
            expected,
            body,
            path,
        )


class ManagedWindowsWorkflowTest(
    ManagedWindowWorkflowFixture, IpLimitWorkflowFixture
):
    async def test_disabled_initial_reservation_then_exact_replay_and_conflict(
        self,
    ):
        subscription, _, _, body, path, _ = await self.setup_closed()
        disabled = await self.client.post(
            path, headers=self.node_headers, json=body
        )
        self.assertEqual(disabled.status_code, 409, disabled.text)
        policy = self.settings.managed_adapter
        assert policy is not None
        self.settings.managed_adapter = policy.model_copy(
            update={"window_mode": "reserved"}
        )
        responses = await asyncio.gather(
            self.client.post(path, headers=self.node_headers, json=body),
            self.client.post(path, headers=self.node_headers, json=body),
        )
        self.assertEqual([row.status_code for row in responses], [200, 200])
        self.assertEqual(
            responses[0].json()["data"], responses[1].json()["data"]
        )
        window = responses[0].json()["data"]
        self.assertEqual(
            hashlib.sha256(window["original_window"].encode()).hexdigest(),
            window["window_sha256"],
        )
        conflict = await self.client.post(
            path,
            headers=self.node_headers,
            json={**body, "requested_bytes": 1025},
        )
        self.assertEqual(conflict.status_code, 409)
        successor = await self.client.post(
            path,
            headers=self.node_headers,
            json={**body, "request_key": "successor_" + self.suffix},
        )
        self.assertEqual(successor.status_code, 409)
        async with self.connection.uow() as fresh:
            rows = await fresh.execute(
                text(
                    "SELECT COUNT(*),SUM(allocated_bytes),SUM(is_closed) "
                    "FROM tbl_usage_grants WHERE subscription_id=:id"
                ),
                {"id": subscription["id"]},
            )
            self.assertEqual(tuple(rows.one()), (1, 1024, 0))
            rows = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_managed_windows "
                    "WHERE subscription_id=:id"
                ),
                {"id": subscription["id"]},
            )
            self.assertEqual(rows.scalar_one(), 1)

    async def test_changed_membership_refuses_new_reservation(self):
        (
            subscription,
            _,
            _,
            body,
            path,
            configuration,
        ) = await self.setup_closed()
        policy = self.settings.managed_adapter
        assert policy is not None
        self.settings.managed_adapter = policy.model_copy(
            update={"window_mode": "reserved"}
        )
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    text(
                        "UPDATE tbl_configurations SET revision=revision+1 "
                        "WHERE id=:id"
                    ),
                    {"id": configuration["id"]},
                )
        response = await self.client.post(
            path, headers=self.node_headers, json=body
        )
        self.assertEqual(response.status_code, 409, response.text)
        async with self.connection.uow() as fresh:
            grants = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_usage_grants "
                    "WHERE subscription_id=:id"
                ),
                {"id": subscription["id"]},
            )
            self.assertEqual(grants.scalar_one(), 0)

    async def test_reservations_on_other_node_share_subscription_quota(self):
        self.fixture_quota = 1024
        subscription, _, _, body, path, _ = await self.setup_closed()
        policy = self.settings.managed_adapter
        assert policy is not None
        self.settings.managed_adapter = policy.model_copy(
            update={"window_mode": "reserved"}
        )
        other = await self.register_assignment(
            subscription["id"], "quota_other"
        )
        async with self.connection.uow() as fresh:
            profile = await fresh.execute(
                text("SELECT id FROM tbl_profiles WHERE configuration_id=:id"),
                {"id": other["configuration_id"]},
            )
            profile_id = profile.scalar_one()
        allocation = await self.client.post(
            f"/v1/nodes/{other['node']['code']}/usage/grants",
            headers={"X-Papilio-Node-Key": other["agent_key"]},
            json={
                "profile_id": profile_id,
                "generation": 0,
                "request_key": "other_reservation_" + self.suffix,
                "requested_bytes": 1024,
            },
        )
        self.assertEqual(allocation.status_code, 200, allocation.text)
        denied = await self.client.post(
            path, headers=self.node_headers, json=body
        )
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertIn("usage_quota_unavailable", denied.text)
        async with self.connection.uow() as fresh:
            count = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_usage_grants "
                    "WHERE subscription_id=:id"
                ),
                {"id": subscription["id"]},
            )
            self.assertEqual(count.scalar_one(), 1)

    async def test_installed_capacity_change_refuses_new_reservation(self):
        subscription, _, _, body, path, _ = await self.setup_closed()
        policy = self.settings.managed_adapter
        assert policy is not None
        changed_capacity = policy.capacity.model_copy(
            update={"max_validity_ms": policy.capacity.max_validity_ms * 2}
        )
        self.settings.managed_adapter = policy.model_copy(
            update={"window_mode": "reserved", "capacity": changed_capacity}
        )
        denied = await self.client.post(
            path, headers=self.node_headers, json=body
        )
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertIn("managed_window_policy_changed", denied.text)
        async with self.connection.uow() as fresh:
            grants = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_usage_grants "
                    "WHERE subscription_id=:id"
                ),
                {"id": subscription["id"]},
            )
            self.assertEqual(grants.scalar_one(), 0)
            windows = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_managed_windows "
                    "WHERE subscription_id=:id"
                ),
                {"id": subscription["id"]},
            )
            self.assertEqual(windows.scalar_one(), 0)
