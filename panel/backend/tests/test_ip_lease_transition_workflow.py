import asyncio
from datetime import UTC, datetime

from papilio.infra.db.transaction import transaction
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.test_ip_limit_workflow import IpLimitWorkflowFixture


class IpLeaseTransitionWorkflowTest(IpLimitWorkflowFixture):
    async def test_policy_transition_rolls_back_on_native_storage_fault(self):
        _, subscription, _ = await self.seed_assigned_subscription()
        id = subscription["id"]
        await self.put_policy(id, enabled=True, maximum=2)
        path = f"/v1/admin/subscriptions/{id}/ip-limit"
        before = (await self.get(path))["data"]
        temporary_table = "owned_ip_sessions_" + self.suffix
        async with self.connection.uow() as unit:
            await unit.execute(
                text(f"RENAME TABLE tbl_ip_sessions TO {temporary_table}")
            )
        try:
            with self.assertRaises(DBAPIError):
                await self.put_policy(id, enabled=True, maximum=1)
        finally:
            async with self.connection.uow() as unit:
                await unit.execute(
                    text(f"RENAME TABLE {temporary_table} TO tbl_ip_sessions")
                )
        after = (await self.get(path))["data"]
        self.assertEqual(after["policy"], before["policy"])
        self.assertEqual(
            after["effective_ip_policy"], before["effective_ip_policy"]
        )
        self.assertEqual(
            after["purchased_ip_policy"], before["purchased_ip_policy"]
        )

    async def test_racing_renewal_cannot_extend_lease_past_captured_barrier(
        self,
    ):
        _, subscription, nodes = await self.seed_assigned_subscription()
        id = subscription["id"]
        await self.put_policy(id, enabled=True, maximum=2)
        issued = await self.admission(nodes[0], id, "192.0.2.89")
        requested, renewed = await asyncio.gather(
            self.put_policy(id, enabled=True, maximum=1),
            self.admission(nodes[1], id, "192.0.2.89"),
        )
        barrier = datetime.fromisoformat(requested["transition"]["retry_at"])
        self.assertGreaterEqual(
            barrier, datetime.fromisoformat(issued["valid_until"])
        )
        if renewed["allowed"]:
            self.assertGreaterEqual(
                barrier, datetime.fromisoformat(renewed["valid_until"])
            )
        else:
            self.assertEqual(renewed["reason"], "ip_policy_draining")
        next_lease = await self.admission(nodes[1], id, "192.0.2.88")
        self.assertFalse(next_lease["allowed"])

    async def test_new_trial_has_complete_history_without_legacy_block(self):
        _, paid, _ = await self.seed_assigned_subscription()
        customer = await self.post(
            "/v1/admin/customers", {"display_name": "Synthetic trial lease"}
        )
        preferences = (await self.get("/v1/admin/settings"))["data"]
        preferences["values"]["trials"].update(
            enabled=True,
            plan_id=paid["plan_id"],
            quota_bytes=1024,
            duration_days=1,
        )
        response = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": preferences["revision"],
                "values": preferences["values"],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        trial = await self.post(
            f"/v1/admin/customers/{customer['id']}/trial",
            {"request_key": "lease_" + self.suffix},
        )
        async with self.connection.uow() as unit:
            persisted = await unit.execute(
                text(
                    "SELECT history_complete,issued_until "
                    "FROM tbl_ip_lease_states WHERE subscription_id=:id"
                ),
                {"id": trial["id"]},
            )
            self.assertEqual(tuple(persisted.one()), (True, None))
        await self.put_policy(trial["id"], enabled=False, maximum=1)
        enabled = await self.put_policy(trial["id"], enabled=True, maximum=1)
        self.assertIsNone(enabled["transition"])

    async def put_policy(self, id, *, enabled, maximum, mode=None, lease=2):
        response = await self.client.put(
            f"/v1/admin/subscriptions/{id}/ip-limit",
            headers=self.headers,
            json={
                "enabled": enabled,
                "max_ips": maximum,
                "lease_seconds": lease,
                "ban_seconds": 3,
                "mode": "reject_new",
                "transition_mode": mode,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    async def test_unlimited_leases_drain_with_replay_and_real_clock_boundary(
        self,
    ):
        _, subscription, nodes = await self.seed_assigned_subscription()
        id = subscription["id"]
        path = f"/v1/admin/subscriptions/{id}/ip-limit"
        bought = (await self.get(path))["data"]["purchased_ip_policy"]
        await self.put_policy(id, enabled=False, maximum=1)
        issued = await self.admission(nodes[0], id, "192.0.2.90")
        self.assertTrue(issued["allowed"])
        preferences = (await self.get("/v1/admin/settings"))["data"]
        preferences["values"]["ip_defaults"]["lease_seconds"] = 1
        updated = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": preferences["revision"],
                "values": preferences["values"],
            },
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.settings.ip_limits.lease_seconds = 1
        self.settings.ip_limits.max_lease_seconds = 1
        requested = await self.put_policy(id, enabled=True, maximum=1, lease=1)
        transition = requested["transition"]
        self.assertEqual(transition["status"], "draining")
        self.assertEqual(transition["retry_at"], issued["valid_until"])
        replay = await self.put_policy(id, enabled=True, maximum=1, lease=1)
        self.assertEqual(replay["transition"], transition)
        detail = (await self.get(path))["data"]
        self.assertFalse(detail["effective_ip_policy"]["policy"]["enabled"])
        self.assertEqual(detail["purchased_ip_policy"], bought)
        rejected = await asyncio.gather(
            self.admission(nodes[0], id, "192.0.2.90"),
            self.admission(nodes[1], id, "192.0.2.91"),
        )
        self.assertTrue(all(not item["allowed"] for item in rejected))
        self.assertTrue(
            all(item["reason"] == "ip_policy_draining" for item in rejected)
        )
        deadline = datetime.fromisoformat(transition["retry_at"])
        ready = asyncio.get_running_loop().create_future()
        timer = asyncio.get_running_loop().call_later(
            max(0, (deadline - datetime.now(UTC)).total_seconds()),
            ready.set_result,
            None,
        )
        try:
            await asyncio.wait_for(ready, 5)
        finally:
            timer.cancel()
        first = await self.admission(nodes[1], id, "192.0.2.91")
        self.assertTrue(first["allowed"])
        second = await self.admission(nodes[0], id, "192.0.2.92")
        self.assertFalse(second["allowed"])
        active = (await self.get(path))["data"]
        self.assertIsNone(active["effective_ip_policy"]["transition"])
        self.assertTrue(active["effective_ip_policy"]["policy"]["enabled"])
        self.assertEqual(active["purchased_ip_policy"], bought)

    async def test_legacy_unknown_history_cannot_guess_a_drain_deadline(self):
        _, subscription, nodes = await self.seed_assigned_subscription()
        id = subscription["id"]
        await self.put_policy(id, enabled=False, maximum=1, lease=120)
        self.assertTrue(
            (await self.admission(nodes[0], id, "192.0.2.95"))["allowed"]
        )
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    text(
                        "DELETE FROM tbl_ip_lease_states "
                        "WHERE subscription_id=:id"
                    ),
                    {"id": id},
                )
        self.settings.ip_limits.max_lease_seconds = 2
        requested = await self.put_policy(id, enabled=True, maximum=1)
        self.assertEqual(
            requested["transition"]["reason"], "legacy_lease_history_unknown"
        )
        self.assertIsNone(requested["transition"]["retry_at"])
        rejected = await self.admission(nodes[1], id, "192.0.2.96")
        self.assertFalse(rejected["allowed"])
        self.assertEqual(rejected["reason"], "legacy_lease_history_unknown")

    async def test_unavailable_closed_receipts_mode_is_explicitly_blocked(
        self,
    ):
        _, subscription, nodes = await self.seed_assigned_subscription()
        id = subscription["id"]
        await self.put_policy(id, enabled=False, maximum=1)
        requested = await self.put_policy(
            id, enabled=True, maximum=1, mode="require_closed_receipts"
        )
        self.assertEqual(
            requested["transition"]["reason"], "closed_receipts_unavailable"
        )
        self.assertIsNone(requested["transition"]["retry_at"])
        rejected = await self.admission(nodes[0], id, "192.0.2.97")
        self.assertFalse(rejected["allowed"])
        self.assertEqual(rejected["reason"], "closed_receipts_unavailable")
        cancelled = await self.put_policy(id, enabled=False, maximum=1)
        self.assertIsNone(cancelled["transition"])
        self.assertTrue(
            (await self.admission(nodes[0], id, "192.0.2.97"))["allowed"]
        )
