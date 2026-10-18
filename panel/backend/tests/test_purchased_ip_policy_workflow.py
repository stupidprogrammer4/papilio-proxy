"""Native purchased terms and subscription-wide API admission (not cores)."""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
from papilio.api.application import create_app
from papilio.infra.db.transaction import transaction
from sqlalchemy import text

from src.config.providers import infrastructure_providers
from src.config.settings import PapilioSettings
from src.modules.sales.subscriptions.interfaces import ISubscriptionCommand
from tests.test_ip_limit_workflow import IpLimitWorkflowFixture


class PurchasedIpPolicyWorkflowTest(IpLimitWorkflowFixture):
    async def test_override_expansion_preserves_purchased_only_presence(self):
        subscription, nodes = await self.explicit_purchase(
            "expansion", enabled=True, max_ips=1
        )
        subscription_id = subscription["id"]
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    text(
                        "DELETE FROM tbl_ip_limit_policies "
                        "WHERE subscription_id=:id"
                    ),
                    {"id": subscription_id},
                )
        first = await self.admission(nodes[0], subscription_id, "192.0.2.70")
        self.assertTrue(first["allowed"])
        await self.configure(subscription_id, max_ips=2)
        path = f"/v1/admin/subscriptions/{subscription_id}/ip-limit"
        persisted = await self.get(path + "/sessions?state=active")
        self.assertEqual(persisted["meta"]["pager"]["total_items"], 1)
        second = await self.admission(nodes[1], subscription_id, "192.0.2.71")
        self.assertTrue(second["allowed"])
        third = await self.admission(nodes[0], subscription_id, "192.0.2.72")
        self.assertFalse(third["allowed"])
        self.assertEqual(third["reason"], "ip_limit_exceeded")
        bought = (await self.get(path))["data"]["purchased_ip_policy"]
        self.assertEqual(bought, subscription["purchased_ip_policy"])

    async def explicit_purchase(self, name, *, enabled, max_ips):
        customer = await self.post(
            "/v1/admin/customers",
            {"display_name": "Synthetic IP buyer " + name},
        )
        policy = {
            "enabled": enabled,
            "max_ips": max_ips,
            "lease_seconds": 120,
            "ban_seconds": 300,
            "mode": "reject_new",
        }
        plan = await self.post(
            "/v1/admin/plans",
            {
                "code": name + "_" + self.suffix,
                "title": "Synthetic source-IP plan",
                "quota_bytes": 1000000,
                "duration_days": 30,
                "price_rial": 100000,
                "ip_limit": policy,
            },
        )
        active = await self.client.patch(
            f"/v1/admin/plans/{plan['id']}/active",
            headers=self.headers,
            json={"is_active": True},
        )
        self.assertEqual(active.status_code, 200, active.text)
        topup = await self.post(
            "/v1/admin/payments/topups",
            {"customer_id": customer["id"], "amount_rial": 300000},
        )
        await self.post(
            f"/v1/admin/payments/topups/{topup['id']}/approve",
            {
                "expected_revision": 1,
                "bank_reference": name + "_" + self.suffix,
            },
        )
        subscription = await self.post(
            "/v1/admin/subscriptions",
            {
                "customer_id": customer["id"],
                "plan_id": plan["id"],
                "purchase_key": name + "_" + self.suffix,
                "auto_renew": True,
            },
        )
        self.assertEqual(subscription["purchased_ip_policy"]["policy"], policy)
        self.assertEqual(
            subscription["purchased_ip_policy"]["source"], "plan_override"
        )
        # API admission fixture boundary: assigned stored profiles, no claim
        # of physically applied core credentials or enforced device count.
        nodes = await asyncio.gather(
            self.register_assignment(subscription["id"], name + "_a"),
            self.register_assignment(subscription["id"], name + "_b"),
        )
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    text(
                        "UPDATE tbl_subscriptions SET status='active',"
                        "provisioning_managed=0 WHERE id=:id"
                    ),
                    {"id": subscription["id"]},
                )
        return subscription, nodes

    async def assert_explicit_admission_and_renewal(
        self, name, enabled, maximum
    ):
        subscription, nodes = await self.explicit_purchase(
            name, enabled=enabled, max_ips=maximum
        )
        first = await self.admission(
            nodes[0], subscription["id"], "192.0.2.61"
        )
        repeated = await self.admission(
            nodes[1], subscription["id"], "::ffff:192.0.2.61"
        )
        self.assertTrue(first["allowed"])
        self.assertTrue(repeated["allowed"])
        # Each HTTP request owns an independent native transaction.
        contenders = await asyncio.gather(
            self.admission(nodes[0], subscription["id"], "192.0.2.62"),
            self.admission(nodes[1], subscription["id"], "192.0.2.63"),
        )
        self.assertEqual(
            sum(row["allowed"] for row in contenders),
            maximum - 1 if enabled else 2,
        )
        bought = subscription["purchased_ip_policy"]
        await self.defaults(enabled=True, max_ips=4)
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    text(
                        "UPDATE tbl_subscriptions SET expires_at=:due "
                        "WHERE id=:id"
                    ),
                    {
                        "due": datetime.now(UTC).replace(tzinfo=None)
                        - timedelta(seconds=1),
                        "id": subscription["id"],
                    },
                )
        async with self.app.state.dishka_container() as scope:
            command = await scope.get(ISubscriptionCommand)
            renewed = await command.renew_due(subscription["id"])
            self.assertEqual(renewed.renewal_count, 1)
        current = (
            await self.get(f"/v1/admin/subscriptions/{subscription['id']}")
        )["data"]
        self.assertEqual(current["purchased_ip_policy"], bought)
        self.assertEqual(
            current["effective_ip_policy"]["policy"], bought["policy"]
        )

    async def test_explicit_one_global_admission_and_renewal(self):
        await self.assert_explicit_admission_and_renewal("one", True, 1)

    async def test_explicit_n_global_admission_and_renewal(self):
        await self.assert_explicit_admission_and_renewal("multiple", True, 2)

    async def test_explicit_unlimited_global_admission_and_renewal(self):
        await self.assert_explicit_admission_and_renewal("unlimited", False, 1)

    async def reload_ip_capacity(self, ceiling: int):
        await self.client.aclose()
        await self.app.state.dishka_container.close()
        self.raw["ip_limits"].update(max_ips_ceiling=ceiling, max_ips=ceiling)
        self.settings = PapilioSettings.model_validate(self.raw)
        self.app = create_app(
            self.settings,
            providers=infrastructure_providers(self.settings),
            middleware=(),
            docs_url=None,
        )
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="https://admin.example.com",
        )
        login = await self.client.post(
            "/v1/admin/auth/login",
            headers={"Origin": self.settings.public.admin_origin},
            json={"username": self.username, "password": self.password},
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.headers = {
            "Origin": self.settings.public.admin_origin,
            "X-CSRF-Token": login.json()["csrf_token"],
        }

    async def defaults(self, *, enabled: bool, max_ips: int):
        current = (await self.get("/v1/admin/settings"))["data"]
        values = current["values"]
        values["ip_defaults"].update(enabled=enabled, max_ips=max_ips)
        response = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={"expected_revision": current["revision"], "values": values},
        )
        self.assertEqual(response.status_code, 200, response.text)

    async def test_snapshot_only_recovery_matches_admission(self):
        await self.defaults(enabled=True, max_ips=1)
        _, subscription, nodes = await self.seed_assigned_subscription()
        current = (
            await self.get(f"/v1/admin/subscriptions/{subscription['id']}")
        )["data"]
        self.assertEqual(
            current["purchased_ip_policy"]["policy"]["max_ips"], 1
        )
        # Explicit isolated recovery fault: only the redundant operational
        # row is lost. The authoritative immutable purchase still exists.
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    text(
                        "DELETE FROM tbl_ip_limit_policies "
                        "WHERE subscription_id=:id"
                    ),
                    {"id": subscription["id"]},
                )
        projected = (
            await self.get(f"/v1/admin/subscriptions/{subscription['id']}")
        )["data"]
        self.assertEqual(
            projected["effective_ip_policy"]["source"], "purchased_snapshot"
        )
        detail = (
            await self.get(
                f"/v1/admin/subscriptions/{subscription['id']}/ip-limit"
            )
        )["data"]
        self.assertEqual(
            detail["effective_ip_policy"], projected["effective_ip_policy"]
        )
        self.assertEqual(
            detail["purchased_ip_policy"], projected["purchased_ip_policy"]
        )
        first = await self.admission(
            nodes[0], subscription["id"], "192.0.2.31"
        )
        second = await self.admission(
            nodes[1], subscription["id"], "192.0.2.32"
        )
        self.assertTrue(first["allowed"])
        self.assertFalse(
            second["allowed"], "Snapshot said one IP while API admitted two"
        )

    async def test_captured_defaults_survive_changes_and_override(self):
        await self.defaults(enabled=False, max_ips=1)
        _, subscription, _ = await self.seed_assigned_subscription()
        bought = subscription["purchased_ip_policy"]
        self.assertFalse(bought["policy"]["enabled"])
        self.assertEqual(bought["source"], "purchase_defaults")
        await self.defaults(enabled=True, max_ips=2)
        after = (
            await self.get(f"/v1/admin/subscriptions/{subscription['id']}")
        )["data"]
        self.assertEqual(after["purchased_ip_policy"], bought)
        self.assertFalse(after["effective_ip_policy"]["policy"]["enabled"])
        await self.configure(subscription["id"], max_ips=1)
        overridden = (
            await self.get(f"/v1/admin/subscriptions/{subscription['id']}")
        )["data"]
        self.assertEqual(overridden["purchased_ip_policy"], bought)
        self.assertTrue(overridden["effective_ip_policy"]["policy"]["enabled"])
        self.assertEqual(
            overridden["effective_ip_policy"]["policy"]["max_ips"], 1
        )

    async def test_tightened_capacity_does_not_overadmit_sold_limit(self):
        await self.defaults(enabled=True, max_ips=3)
        _, subscription, nodes = await self.seed_assigned_subscription()
        self.assertEqual(
            subscription["purchased_ip_policy"]["policy"]["max_ips"], 3
        )
        await self.reload_ip_capacity(1)
        first = await self.admission(
            nodes[0], subscription["id"], "192.0.2.41"
        )
        second = await self.admission(
            nodes[1], subscription["id"], "192.0.2.42"
        )
        third = await self.admission(
            nodes[0], subscription["id"], "192.0.2.43"
        )
        fourth = await self.admission(
            nodes[1], subscription["id"], "192.0.2.44"
        )
        self.assertTrue(first["allowed"])
        self.assertTrue(second["allowed"])
        self.assertTrue(third["allowed"])
        self.assertFalse(
            fourth["allowed"], "Tightened reader cap hid active IPs"
        )
