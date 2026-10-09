import asyncio
from datetime import UTC, datetime, timedelta

from papilio.infra.db.transaction import transaction
from sqlalchemy import select, update
from sqlmodel import col

from src.modules.accounts.staff.app.passwords import Passwords
from src.modules.accounts.staff.domain.models import StaffModel
from src.modules.accounts.staff.infra.mysql import StaffRepository
from src.modules.network.ip_limits.infra.tables import IpSessionTable
from src.modules.sales.subscriptions.infra.tables import SubscriptionTable
from tests.test_automation_workflow import AutomationWorkflowFixture


class IpLimitWorkflowFixture(AutomationWorkflowFixture):
    async def seed_assigned_subscription(self):
        customer, subscription = await self.paid_subscription()
        nodes = await asyncio.gather(
            *(
                self.register_assignment(subscription["id"], name)
                for name in ("a", "b")
            )
        )
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    update(SubscriptionTable)
                    .where(col(SubscriptionTable.id) == subscription["id"])
                    .values(status="active", provisioning_managed=False)
                )
        return customer, subscription, nodes

    async def register_assignment(self, subscription_id, name):
        registered = await self.post(
            "/v1/admin/network/nodes",
            {
                "code": f"ip_{name}_{self.suffix}",
                "label": "نود محدودیت IP",
                "public_host": "example.invalid",
                "public_port": 443,
                "protocol": "vless_reality",
            },
        )
        node = registered["node"]
        enabled = await self.client.patch(
            f"/v1/admin/network/nodes/{node['id']}/enabled",
            headers=self.headers,
            json={"enabled": True},
        )
        self.assertEqual(enabled.status_code, 200)
        configuration = await self.post(
            "/v1/admin/network/configurations",
            {
                "node_id": node["id"],
                "label": "کانفیگ محدودیت",
                "options": {
                    "protocol": "vless_reality",
                    "listen_address": "0.0.0.0",
                    "server_name": "example.com",
                    "target_port": 443,
                },
            },
        )
        await self.post(
            f"/v1/admin/network/configurations/{configuration['id']}/profiles",
            {"subscription_id": subscription_id},
        )
        registered["configuration_id"] = configuration["id"]
        return registered

    async def configure(self, subscription_id, mode="reject_new", max_ips=1):
        response = await self.client.put(
            f"/v1/admin/subscriptions/{subscription_id}/ip-limit",
            headers=self.headers,
            json={
                "enabled": True,
                "max_ips": max_ips,
                "lease_seconds": 120,
                "ban_seconds": 300,
                "mode": mode,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

    async def admission(self, node, subscription_id, address):
        response = await self.client.post(
            f"/v1/nodes/{node['node']['code']}/ip-admission",
            headers={"X-Papilio-Node-Key": node["agent_key"]},
            json={"subscription_id": subscription_id, "source_ip": address},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]


class IpLimitWorkflowTest(IpLimitWorkflowFixture):
    async def test_tightening_does_not_issue_overlapping_new_lease(self):
        _, subscription, nodes = await self.seed_assigned_subscription()
        subscription_id = subscription["id"]
        await self.configure(subscription_id, max_ips=2)
        self.assertTrue(
            (await self.admission(nodes[0], subscription_id, "192.0.2.80"))[
                "allowed"
            ]
        )
        self.assertTrue(
            (await self.admission(nodes[1], subscription_id, "192.0.2.81"))[
                "allowed"
            ]
        )
        await self.configure(subscription_id, max_ips=1)
        replacement = await self.admission(
            nodes[0], subscription_id, "192.0.2.82"
        )
        self.assertFalse(replacement["allowed"])

    async def test_expansion_preserves_active_presence_across_nodes(self):
        _, subscription, nodes = await self.seed_assigned_subscription()
        subscription_id = subscription["id"]
        await self.configure(subscription_id)
        first = await self.admission(nodes[0], subscription_id, "192.0.2.60")
        self.assertTrue(first["allowed"])
        await self.configure(subscription_id, max_ips=2)
        path = f"/v1/admin/subscriptions/{subscription_id}/ip-limit"
        persisted = await self.get(path + "/sessions?state=active")
        self.assertEqual(persisted["meta"]["pager"]["total_items"], 1)
        second = await self.admission(nodes[1], subscription_id, "192.0.2.61")
        self.assertTrue(second["allowed"])
        await self.configure(subscription_id, max_ips=2)
        third = await self.admission(nodes[0], subscription_id, "192.0.2.62")
        self.assertFalse(third["allowed"])
        self.assertEqual(third["reason"], "ip_limit_exceeded")
        first_again = await self.admission(
            nodes[1], subscription_id, "::ffff:192.0.2.60"
        )
        self.assertTrue(first_again["allowed"])
        persisted = await self.get(path + "/sessions?state=active")
        self.assertEqual(persisted["meta"]["pager"]["total_items"], 2)

    async def test_update_scope_can_manage_existing_ip_restrictions(self):
        _, subscription, nodes = await self.seed_assigned_subscription()
        subscription_id = subscription["id"]
        await self.configure(subscription_id)
        await self.admission(nodes[0], subscription_id, "192.0.2.99")
        path = f"/v1/admin/subscriptions/{subscription_id}/ip-limit"
        sessions = await self.get(path + "/sessions")
        session_id = sessions["data"][0]["id"]
        username = "ip_operator_" + self.suffix
        hashed = await Passwords(self.settings).hash(self.password)
        async with self.connection.uow() as unit:
            async with transaction(unit):
                repository = StaffRepository(unit)
                staff = await repository.create(
                    StaffModel(
                        username=username, password_hash=hashed, is_active=True
                    )
                )
                await repository.add_grant(staff.id, "subscriptions:read")
                await repository.add_grant(staff.id, "subscriptions:update")
        login = await self.client.post(
            "/v1/admin/auth/login",
            headers={"Origin": self.settings.public.admin_origin},
            json={"username": username, "password": self.password},
        )
        self.assertEqual(login.status_code, 200)
        headers = {
            "Origin": self.settings.public.admin_origin,
            "X-CSRF-Token": login.json()["csrf_token"],
        }
        ban = await self.client.post(
            path + f"/sessions/{session_id}/ban",
            headers=headers,
            json={"seconds": 30, "reason": "تأیید دسترسی ویرایش"},
        )
        self.assertEqual(ban.status_code, 200, ban.text)
        unban = await self.client.post(
            path + f"/sessions/{session_id}/unban", headers=headers
        )
        self.assertEqual(unban.status_code, 200, unban.text)

    async def test_shared_limit_concurrency_normalization_and_manual_recovery(
        self,
    ):
        _, subscription, nodes = await self.seed_assigned_subscription()
        subscription_id = subscription["id"]
        path = f"/v1/admin/subscriptions/{subscription_id}/ip-limit"
        detail = await self.get(path)
        self.assertIsNone(detail["data"]["policy"])
        await self.configure(subscription_id)
        results = await asyncio.gather(
            *(
                self.admission(node, subscription_id, address)
                for node, address in zip(
                    nodes, ("192.0.2.10", "2001:db8::10"), strict=True
                )
            )
        )
        self.assertEqual(sum(row["allowed"] for row in results), 1)
        allowed = next(row for row in results if row["allowed"])
        denied = next(row for row in results if not row["allowed"])
        self.assertEqual(denied["reason"], "ip_limit_exceeded")
        repeated = await self.admission(
            nodes[1], subscription_id, allowed["source_ip"]
        )
        self.assertTrue(repeated["allowed"])
        denied_again = await self.admission(
            nodes[0], subscription_id, denied["source_ip"]
        )
        self.assertFalse(denied_again["allowed"])
        self.assertEqual(
            denied_again["blocked_until"], denied["blocked_until"]
        )
        async with self.connection.uow() as unit:
            persisted = await unit.execute(
                select(IpSessionTable).where(
                    col(IpSessionTable.subscription_id) == subscription_id
                )
            )
            sessions = list(persisted.scalars().all())
        self.assertEqual(len(sessions), 2)
        active = next(
            row for row in sessions if row.source_ip == allowed["source_ip"]
        )
        blocked = next(
            row for row in sessions if row.source_ip == denied["source_ip"]
        )
        listed = await self.get(path + "/sessions?state=blocked&per_page=1")
        self.assertEqual(listed["meta"]["pager"]["total_items"], 1)
        self.assertEqual(listed["data"][0]["source_ip"], denied["source_ip"])
        self.assertTrue(listed["data"][0]["blocked_until"].endswith("Z"))
        await self.post(
            path + f"/sessions/{active.id}/ban",
            {"seconds": 30, "reason": "محدودیت آزمایشی"},
        )
        self.assertFalse(
            (
                await self.admission(
                    nodes[0], subscription_id, active.source_ip
                )
            )["allowed"]
        )
        await self.post(path + f"/sessions/{blocked.id}/unban")
        self.assertTrue(
            (
                await self.admission(
                    nodes[1], subscription_id, blocked.source_ip
                )
            )["allowed"]
        )
        if blocked.source_ip.startswith("2001:"):
            normalized = await self.admission(
                nodes[0], subscription_id, "2001:0db8:0:0:0:0:0:10"
            )
        else:
            normalized = await self.admission(
                nodes[0], subscription_id, "::ffff:192.0.2.10"
            )
        self.assertTrue(normalized["allowed"])
        listed = await self.get(path + "/sessions?state=active")
        self.assertEqual(listed["meta"]["pager"]["total_items"], 1)

    async def test_oldest_replacement_expiry_and_subscription_isolation(self):
        customer, subscription, nodes = await self.seed_assigned_subscription()
        subscription_id = subscription["id"]
        path = f"/v1/admin/subscriptions/{subscription_id}/ip-limit"
        await self.configure(subscription_id, "replace_oldest")
        self.assertTrue(
            (await self.admission(nodes[0], subscription_id, "192.0.2.40"))[
                "allowed"
            ]
        )
        self.assertTrue(
            (
                await self.admission(
                    nodes[1], subscription_id, "::ffff:192.0.2.40"
                )
            )["allowed"]
        )
        self.assertTrue(
            (await self.admission(nodes[1], subscription_id, "2001:db8::41"))[
                "allowed"
            ]
        )
        self.assertTrue(
            (
                await self.admission(
                    nodes[0], subscription_id, "2001:0db8:0:0:0:0:0:41"
                )
            )["allowed"]
        )
        self.assertFalse(
            (await self.admission(nodes[0], subscription_id, "192.0.2.40"))[
                "allowed"
            ]
        )
        blocked = await self.get(path + "/sessions?state=blocked")
        self.assertEqual(blocked["data"][0]["block_reason"], "replaced_oldest")
        second = await self.post(
            "/v1/admin/subscriptions",
            {
                "customer_id": customer["id"],
                "plan_id": subscription["plan_id"],
                "purchase_key": "second_" + self.suffix,
                "auto_renew": False,
            },
        )
        foreign_unban = await self.client.post(
            f"/v1/admin/subscriptions/{second['id']}/ip-limit/sessions/{blocked['data'][0]['id']}/unban",
            headers=self.headers,
        )
        self.assertEqual(foreign_unban.status_code, 404)
        await self.post(
            f"/v1/admin/network/configurations/{nodes[0]['configuration_id']}/profiles",
            {"subscription_id": second["id"]},
        )
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    update(SubscriptionTable)
                    .where(col(SubscriptionTable.id) == second["id"])
                    .values(status="active", provisioning_managed=False)
                )
        await self.configure(second["id"])
        self.assertTrue(
            (await self.admission(nodes[0], second["id"], "192.0.2.40"))[
                "allowed"
            ]
        )
        unassigned = await self.client.post(
            f"/v1/nodes/{nodes[1]['node']['code']}/ip-admission",
            headers={"X-Papilio-Node-Key": nodes[1]["agent_key"]},
            json={"subscription_id": second["id"], "source_ip": "192.0.2.40"},
        )
        self.assertEqual(unassigned.status_code, 409)
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    update(IpSessionTable)
                    .where(
                        col(IpSessionTable.subscription_id) == subscription_id
                    )
                    .values(
                        expires_at=datetime.now(UTC).replace(tzinfo=None)
                        - timedelta(seconds=1),
                        blocked_until=datetime.now(UTC).replace(tzinfo=None)
                        - timedelta(seconds=1),
                    )
                )
        self.assertTrue(
            (await self.admission(nodes[0], subscription_id, "192.0.2.40"))[
                "allowed"
            ]
        )
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    update(SubscriptionTable)
                    .where(col(SubscriptionTable.id) == subscription_id)
                    .values(
                        expires_at=datetime.now(UTC).replace(tzinfo=None)
                        - timedelta(seconds=1)
                    )
                )
        decision = await self.admission(
            nodes[0], subscription_id, "192.0.2.40"
        )
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason"], "entitlement_inactive")

    async def test_identity_permissions_validation_and_inactive_nodes(self):
        _, subscription, nodes = await self.seed_assigned_subscription()
        subscription_id = subscription["id"]
        node = nodes[0]
        path = f"/v1/admin/subscriptions/{subscription_id}/ip-limit"
        endpoint = f"/v1/nodes/{node['node']['code']}/ip-admission"
        body = {"subscription_id": subscription_id, "source_ip": "192.0.2.50"}
        denied = await self.client.post(endpoint, json=body)
        self.assertEqual(denied.status_code, 401)
        invalid = await self.client.post(
            endpoint,
            headers={"X-Papilio-Node-Key": node["agent_key"]},
            json={**body, "source_ip": "fe80::1%eth0"},
        )
        self.assertEqual(invalid.status_code, 422)
        capacity = await self.client.put(
            path,
            headers=self.headers,
            json={
                "enabled": True,
                "max_ips": self.settings.ip_limits.max_ips_ceiling + 1,
                "lease_seconds": 120,
                "ban_seconds": 300,
                "mode": "reject_new",
            },
        )
        self.assertEqual(capacity.status_code, 409)
        self.assertIsNone((await self.get(path))["data"]["policy"])
        disabled = await self.client.patch(
            f"/v1/admin/network/nodes/{node['node']['id']}/enabled",
            headers=self.headers,
            json={"enabled": False},
        )
        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(
            (await self.admission(node, subscription_id, "192.0.2.50"))[
                "allowed"
            ]
        )
        hashed = await Passwords(self.settings).hash("readonly-password")
        async with self.connection.uow() as unit:
            async with transaction(unit):
                repository = StaffRepository(unit)
                staff = await repository.create(
                    StaffModel(
                        username="ip_reader_" + self.suffix,
                        password_hash=hashed,
                        is_active=True,
                    )
                )
                await repository.add_grant(staff.id, "subscriptions:read")
        login = await self.client.post(
            "/v1/admin/auth/login",
            headers={"Origin": self.settings.public.admin_origin},
            json={
                "username": "ip_reader_" + self.suffix,
                "password": "readonly-password",
            },
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual((await self.client.get(path)).status_code, 200)
        forbidden = await self.client.put(
            path,
            headers={
                "Origin": self.settings.public.admin_origin,
                "X-CSRF-Token": login.json()["csrf_token"],
            },
            json={
                "enabled": True,
                "max_ips": 1,
                "lease_seconds": 120,
                "ban_seconds": 300,
                "mode": "reject_new",
            },
        )
        self.assertEqual(forbidden.status_code, 403)
        readonly_headers = {
            "Origin": self.settings.public.admin_origin,
            "X-CSRF-Token": login.json()["csrf_token"],
        }
        self.assertEqual(
            (await self.client.get(path + "/sessions")).status_code, 200
        )
        unban = await self.client.post(
            path + "/sessions/1/unban", headers=readonly_headers
        )
        self.assertEqual(unban.status_code, 403)
        ban = await self.client.post(
            path + "/sessions/1/ban",
            headers=readonly_headers,
            json={"seconds": 30, "reason": "آزمون دسترسی"},
        )
        self.assertEqual(ban.status_code, 403)
