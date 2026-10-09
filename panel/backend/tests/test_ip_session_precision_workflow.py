import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from .test_ip_limit_workflow import IpLimitWorkflowFixture


class IpSessionPrecisionWorkflowTest(IpLimitWorkflowFixture):
    async def test_committed_presence_matches_granted_lease(self):
        _, subscription, nodes = await self.seed_assigned_subscription()
        id = subscription["id"]
        policy = await self.client.put(
            f"/v1/admin/subscriptions/{id}/ip-limit",
            headers=self.headers,
            json={
                "enabled": True,
                "max_ips": 1,
                "lease_seconds": 2,
                "ban_seconds": 3,
                "mode": "reject_new",
            },
        )
        self.assertEqual(policy.status_code, 200, policy.text)
        async with self.connection.uow() as unit:
            clock = await unit.execute(text("SELECT UTC_TIMESTAMP(6)"))
            phase = clock.scalar_one().replace(microsecond=250000)
        if phase <= datetime.now(UTC).replace(tzinfo=None):
            phase += timedelta(seconds=1)
        phase_ready = asyncio.get_running_loop().create_future()
        phase_timer = asyncio.get_running_loop().call_later(
            max(
                0,
                (
                    phase - datetime.now(UTC).replace(tzinfo=None)
                ).total_seconds(),
            ),
            phase_ready.set_result,
            None,
        )
        try:
            await asyncio.wait_for(phase_ready, 3)
        finally:
            phase_timer.cancel()
        admitted = await self.admission(nodes[0], id, "192.0.2.160")
        self.assertTrue(admitted["allowed"])
        deadline = datetime.fromisoformat(admitted["valid_until"])
        async with self.connection.uow() as unit:
            result = await unit.execute(
                text(
                    "SELECT expires_at FROM tbl_ip_sessions "
                    "WHERE subscription_id=:id AND source_ip=:ip"
                ),
                {"id": id, "ip": "192.0.2.160"},
            )
            persisted = result.scalar_one()
        with self.subTest("committed deadline"):
            self.assertEqual(persisted, deadline.replace(tzinfo=None))
        # A different source cannot use the fraction discarded by DATETIME(0).
        boundary = deadline.replace(microsecond=0)
        ready = asyncio.get_running_loop().create_future()
        timer = asyncio.get_running_loop().call_later(
            max(0, (boundary - datetime.now(UTC)).total_seconds()),
            ready.set_result,
            None,
        )
        try:
            await asyncio.wait_for(ready, 5)
        finally:
            timer.cancel()
        second = await self.admission(nodes[1], id, "192.0.2.161")
        self.assertLess(datetime.now(UTC), deadline)
        self.assertFalse(second["allowed"])
        self.assertEqual(second["reason"], "ip_limit_exceeded")
