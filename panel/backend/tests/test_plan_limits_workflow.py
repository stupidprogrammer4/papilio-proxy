import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlmodel import col

from src.modules.sales.subscriptions.infra.tables import SubscriptionTable
from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowTest,
)
from tests.test_usage_workflow import UsageWorkflowTest


class PlanLimitsWorkflowTest(
    StaffAdministrationWorkflowTest, UsageWorkflowTest
):
    async def exercise_limits(self, quota, duration):
        subscription, request, nodes, purchase = await self.setup_sale(
            protocols=("vless_reality",),
            quota_bytes=quota,
            duration_days=duration,
            renewal_trigger="either",
            quota_policy={
                **self.raw["usage"]["policy"],
                "mode": "reserved",
                "grant_bytes": 2000,
            },
        )
        sid = subscription["id"]
        self.assertEqual(subscription["quota_bytes"], quota)
        self.assertEqual(subscription["duration_days"], duration)
        self.assertEqual(subscription["expires_at"] is None, duration is None)
        # A catalog edit must not change an existing paid entitlement.
        changed = await self.client.patch(
            f"/v1/admin/plans/{purchase['plan_id']}",
            headers=self.headers,
            json={"quota_bytes": 5000, "duration_days": 15},
        )
        self.assertEqual(changed.status_code, 200)
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        tasks = (
            await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
        )["data"]
        node, claim = await self.claim(tasks[0], nodes)
        self.assertEqual(claim["quota_bytes"], quota)
        self.assertEqual(claim["expires_at"] is None, duration is None)
        await self.ack(tasks[0], node, claim)
        url = (
            await self.post(
                f"/v1/admin/network/configurations/subscriptions/{sid}/link"
            )
        )["url"]
        self.assertEqual(
            (
                await self.client.get("/s/" + url.rsplit("/", 1)[-1])
            ).status_code,
            200,
        )
        status = await self.client.get(
            "/s/" + url.rsplit("/", 1)[-1] + "/status"
        )
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["data"]["quota_bytes"], quota)
        self.assertEqual(
            status.json()["data"]["expires_at"] is None, duration is None
        )
        admitted = await self.client.post(
            f"/v1/nodes/{node['node']['code']}/ip-admission",
            headers={"X-Papilio-Node-Key": node["agent_key"]},
            json={"subscription_id": sid, "source_ip": "192.0.2.41"},
        )
        self.assertEqual(admitted.status_code, 200)
        self.assertTrue(admitted.json()["data"]["allowed"])
        self.assertIsNotNone(admitted.json()["data"]["valid_until"])
        first = await self.allocate(tasks[0], nodes, 1000)
        self.assertEqual(first.status_code, 200)
        grant = first.json()["data"]
        self.assertIsNotNone(grant["valid_until"])
        final = await self.usage(grant, tasks[0], nodes, 500, 500, final=True)
        self.assertEqual(final.status_code, 200)
        current = (await self.get(f"/v1/admin/subscriptions/{sid}"))["data"]
        self.assertEqual(current["quota_bytes"], quota)
        self.assertEqual(current["duration_days"], duration)
        if quota is None:
            # Unlimited volume retains bounded grants and usage accounting.
            second = await self.allocate(tasks[0], nodes, 2000, "unlimited")
            self.assertEqual(second.status_code, 200)
            closed = await self.usage(
                second.json()["data"], tasks[0], nodes, 1000, 1000, final=True
            )
            self.assertEqual(closed.status_code, 200)
            alive = await self.post(
                f"/v1/admin/subscriptions/{sid}/check-lifecycle"
            )
            self.assertEqual(alive["status"], "active")
            async with self.connection.uow() as independent:
                await independent.execute(
                    update(SubscriptionTable)
                    .where(col(SubscriptionTable.id) == sid)
                    .values(
                        expires_at=datetime.now(UTC).replace(tzinfo=None)
                        - timedelta(seconds=1)
                    )
                )
                await independent.commit()
        else:
            denied = await self.allocate(tasks[0], nodes, 1, "exhausted")
            self.assertEqual(denied.status_code, 409)
        if duration is None:
            from tests.scheduler_runtime import exercise_native_lifecycle

            observed = await asyncio.to_thread(
                exercise_native_lifecycle, self.raw, sid, "quota"
            )
            self.assertEqual(observed, ("revoking", "quota"))
        ended = await self.post(
            f"/v1/admin/subscriptions/{sid}/check-lifecycle"
        )
        self.assertEqual(ended["status"], "revoking")
        self.assertEqual(
            (
                await self.client.get("/s/" + url.rsplit("/", 1)[-1])
            ).status_code,
            404,
        )
        node, revoke = await self.claim(tasks[0], nodes)
        await self.ack(tasks[0], node, revoke, outcome="revoked")
        renewed = await asyncio.gather(self.renew(sid), self.renew(sid))
        self.assertEqual(renewed, [1, 1])
        wallet = (
            await self.get(
                f"/v1/admin/payments/wallets/{subscription['customer_id']}"
            )
        )["data"]
        self.assertEqual(wallet["balance_rial"], 100000)
        async with self.connection.uow() as independent:
            row = (
                await independent.execute(
                    select(SubscriptionTable).where(
                        col(SubscriptionTable.id) == sid
                    )
                )
            ).scalar_one()
            self.assertEqual(row.quota_bytes, quota)
            self.assertEqual(row.duration_days, duration)
            self.assertEqual(row.expires_at is None, duration is None)
            self.assertEqual(row.used_bytes, 0)

    async def test_quota_with_expiry(self):
        await self.exercise_limits(1000, 30)

    async def test_quota_without_expiry(self):
        await self.exercise_limits(1000, None)

    async def test_unlimited_quota_with_expiry(self):
        await self.exercise_limits(None, 30)

    async def test_plan_mode_edits_validate_combined_limits(self):
        created = await self.post(
            "/v1/admin/plans",
            {
                "code": "limits_" + self.suffix,
                "title": "پلن حجمی",
                "quota_bytes": 1000,
                "duration_days": None,
                "price_rial": 100000,
            },
        )
        path = f"/v1/admin/plans/{created['id']}"
        invalid = await self.client.patch(
            path, headers=self.headers, json={"quota_bytes": None}
        )
        self.assertEqual(invalid.status_code, 400)
        unchanged = (await self.get(path))["data"]
        self.assertEqual(unchanged["quota_bytes"], 1000)
        converted = await self.client.patch(
            path,
            headers=self.headers,
            json={"quota_bytes": None, "duration_days": 30},
        )
        self.assertEqual(converted.status_code, 200)
        self.assertIsNone(converted.json()["data"]["quota_bytes"])
        unbounded = await self.client.post(
            "/v1/admin/plans",
            headers=self.headers,
            json={
                "code": "invalid_" + self.suffix,
                "title": "بدون هیچ محدودیت",
                "quota_bytes": None,
                "duration_days": None,
                "price_rial": 100000,
            },
        )
        self.assertEqual(unbounded.status_code, 422)

    async def test_concurrent_limit_clears_keep_one_limit(self):
        created = await self.post(
            "/v1/admin/plans",
            {
                "code": "parallel_" + self.suffix,
                "title": "حجمی مدت‌دار",
                "quota_bytes": 1000,
                "duration_days": 30,
                "price_rial": 100000,
            },
        )
        path = f"/v1/admin/plans/{created['id']}"
        responses = await asyncio.gather(
            self.client.patch(
                path, headers=self.headers, json={"quota_bytes": None}
            ),
            self.client.patch(
                path, headers=self.headers, json={"duration_days": None}
            ),
        )
        self.assertEqual(
            sorted(row.status_code for row in responses), [200, 400]
        )
        fresh = (await self.get(path))["data"]
        self.assertTrue(
            fresh["quota_bytes"] is not None
            or fresh["duration_days"] is not None
        )

    async def test_populated_limit_migration_and_guarded_downgrade(self):
        from unittest.mock import patch

        from alembic import command
        from alembic.config import Config

        subscription, _, _, _ = await self.setup_sale(
            protocols=("vless_reality",)
        )
        assert self.settings.db is not None
        migration = Config("alembic.ini")
        migration.set_main_option("sqlalchemy.url", self.settings.db.dsn)
        async with self.connection.uow() as independent:
            before = (
                (
                    await independent.execute(
                        select(SubscriptionTable).where(
                            col(SubscriptionTable.id) == subscription["id"]
                        )
                    )
                )
                .scalar_one()
                .model_dump()
            )
        with patch.dict("os.environ", {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(
                command.downgrade, migration, "0036_openvpn_management_sockets"
            )
            await asyncio.to_thread(command.upgrade, migration, "head")
        async with self.connection.uow() as independent:
            after = (
                (
                    await independent.execute(
                        select(SubscriptionTable).where(
                            col(SubscriptionTable.id) == subscription["id"]
                        )
                    )
                )
                .scalar_one()
                .model_dump()
            )
        self.assertEqual(after, before)
        await self.post(
            "/v1/admin/plans",
            {
                "code": "no_expiry_" + self.suffix,
                "title": "بدون مدت",
                "quota_bytes": 1000,
                "duration_days": None,
                "price_rial": 100000,
            },
        )
        with patch.dict("os.environ", {"PAPILIO_CONFIG": "config.yml.sample"}):
            with self.assertRaisesRegex(
                RuntimeError, "Independent plan limits"
            ):
                await asyncio.to_thread(
                    command.downgrade,
                    migration,
                    "0036_openvpn_management_sockets",
                )
        from sqlalchemy import text

        async with self.connection.uow() as independent:
            head = (
                await independent.execute(
                    text("SELECT version_num FROM alembic_version")
                )
            ).scalar_one()
        self.assertEqual(head, "0037_plan_limits")
