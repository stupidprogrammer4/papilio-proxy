import asyncio
from contextvars import Context
from datetime import UTC, datetime

from papilio.infra.db.transaction import transaction
from papilio.security.crypto import hash_sha256
from sqlalchemy import text

from .lock_observation import MySQLLockObservation
from .test_ip_limit_workflow import IpLimitWorkflowFixture


class UsageReportKeyWorkflowTest(IpLimitWorkflowFixture):
    async def test_rotated_key_report_refuses_counters_then_recovers_once(
        self,
    ):
        customer, subscription, nodes = await self.seed_assigned_subscription()
        id = subscription["id"]
        node = nodes[0]
        async with self.connection.uow() as unit:
            profiles = await unit.execute(
                text(
                    "SELECT id FROM tbl_profiles WHERE subscription_id=:id "
                    "AND configuration_id=:configuration"
                ),
                {"id": id, "configuration": node["configuration_id"]},
            )
            profile_id = profiles.scalar_one()
        allocation = await self.client.post(
            f"/v1/nodes/{node['node']['code']}/usage/grants",
            headers={"X-Papilio-Node-Key": node["agent_key"]},
            json={
                "profile_id": profile_id,
                "generation": 0,
                "request_key": "report_key_" + self.suffix,
                "requested_bytes": 1024,
            },
        )
        self.assertEqual(allocation.status_code, 200)
        grant = allocation.json()["data"]
        path = (
            f"/v1/nodes/{node['node']['code']}/usage/grants/"
            f"{grant['id']}/reports"
        )
        body = {
            "event_id": "report_rotated_" + self.suffix,
            "sequence": 1,
            "upload_bytes": 120,
            "download_bytes": 30,
            "sampled_at": datetime.now(UTC).isoformat(),
            "final": True,
        }
        new_key = "synthetic-report-replacement-key"
        new_digest = await asyncio.to_thread(hash_sha256, new_key)
        report = None
        try:
            async with self.connection.uow() as holder:
                async with transaction(holder):
                    await holder.execute(
                        text(
                            "SELECT id FROM tbl_nodes WHERE id=:id FOR UPDATE"
                        ),
                        {"id": node["node"]["id"]},
                    )
                    report = asyncio.create_task(
                        self.client.post(
                            path,
                            headers={"X-Papilio-Node-Key": node["agent_key"]},
                            json=body,
                        ),
                        context=Context(),
                    )
                    observed = await asyncio.to_thread(
                        MySQLLockObservation().wait_for_queries,
                        self.raw["db"]["dsn"],
                        "tbl_nodes",
                        ("SELECT",),
                        1,
                        5,
                        0.02,
                        True,
                    )
                    self.assertTrue(
                        observed, "Native report Node wait missing"
                    )
                    await holder.execute(
                        text(
                            "UPDATE tbl_nodes SET agent_key_hash=:digest "
                            "WHERE id=:id"
                        ),
                        {"id": node["node"]["id"], "digest": new_digest},
                    )
            response = await asyncio.wait_for(report, 12)
            self.assertEqual(response.status_code, 401)
        finally:
            if report is not None and not report.done():
                report.cancel()
                await asyncio.gather(report, return_exceptions=True)
        async with self.connection.uow() as fresh:
            denied_grant = await fresh.execute(
                text(
                    "SELECT "
                    "upload_bytes,download_bytes,sequence,is_closed FROM "
                    "tbl_usage_grants WHERE id=:id"
                ),
                {"id": grant["id"]},
            )
            self.assertEqual(tuple(denied_grant.one()), (0, 0, 0, False))
            denied_events = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_usage_events WHERE grant_id=:id"
                ),
                {"id": grant["id"]},
            )
            self.assertEqual(denied_events.scalar_one(), 0)
            denied_usage = await fresh.execute(
                text("SELECT used_bytes FROM tbl_subscriptions WHERE id=:id"),
                {"id": id},
            )
            self.assertEqual(denied_usage.scalar_one(), 0)
            balance = await fresh.execute(
                text(
                    "SELECT balance_rial FROM tbl_wallets WHERE "
                    "customer_id=:id"
                ),
                {"id": customer["id"]},
            )
            self.assertEqual(balance.scalar_one(), 200000)
        accepted = await self.client.post(
            path,
            headers={"X-Papilio-Node-Key": new_key},
            json=body,
        )
        self.assertEqual(accepted.status_code, 200)
        replay = await self.client.post(
            path,
            headers={"X-Papilio-Node-Key": new_key},
            json=body,
        )
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(
            replay.json()["data"]["id"], accepted.json()["data"]["id"]
        )
        async with self.connection.uow() as fresh:
            accepted_grant = await fresh.execute(
                text(
                    "SELECT "
                    "upload_bytes,download_bytes,sequence,is_closed FROM "
                    "tbl_usage_grants WHERE id=:id"
                ),
                {"id": grant["id"]},
            )
            self.assertEqual(tuple(accepted_grant.one()), (120, 30, 1, True))
            accepted_events = await fresh.execute(
                text(
                    "SELECT COUNT(*),SUM(delta_bytes) FROM "
                    "tbl_usage_events WHERE grant_id=:id"
                ),
                {"id": grant["id"]},
            )
            self.assertEqual(tuple(accepted_events.one()), (1, 150))
            accepted_usage = await fresh.execute(
                text("SELECT used_bytes FROM tbl_subscriptions WHERE id=:id"),
                {"id": id},
            )
            self.assertEqual(accepted_usage.scalar_one(), 150)
            balance = await fresh.execute(
                text(
                    "SELECT balance_rial FROM tbl_wallets WHERE "
                    "customer_id=:id"
                ),
                {"id": customer["id"]},
            )
            self.assertEqual(balance.scalar_one(), 200000)
        current = (await self.get(f"/v1/admin/subscriptions/{id}"))["data"]
        self.assertEqual(
            current["purchased_ip_policy"], subscription["purchased_ip_policy"]
        )
