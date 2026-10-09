import asyncio
import base64

from papilio.infra.db.transaction import transaction
from sqlalchemy import select, update
from sqlmodel import col

from src.modules.accounts.staff.app.passwords import Passwords
from src.modules.accounts.staff.domain.models import StaffModel
from src.modules.accounts.staff.infra.mysql import StaffRepository
from src.modules.network.configurations.infra.tables import ConfigurationTable
from src.modules.sales.subscriptions.infra.tables import SubscriptionTable
from tests.test_automation_workflow import AutomationWorkflowFixture


class FoundationsWorkflowTest(AutomationWorkflowFixture):
    async def put(self, path, data):
        response = await self.client.put(path, headers=self.headers, json=data)
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]

    async def node(self):
        result = await self.post(
            "/v1/admin/network/nodes",
            {
                "code": "foundation_" + self.suffix,
                "label": "نود پایه",
                "public_host": "origin.example.invalid",
                "public_port": 443,
                "protocol": "vless_reality",
            },
        )
        return result

    async def inbound(self, node_id, core_id=None, port=443):
        result = await self.post(
            "/v1/admin/network/configurations",
            {
                "node_id": node_id,
                "core_id": core_id,
                "listen_port": port,
                "label": "ورودی پایه",
                "options": self.options(),
            },
        )
        return result

    def options(self):
        return {
            "protocol": "vless_reality",
            "listen_address": "0.0.0.0",
            "server_name": "example.com",
            "target_port": 443,
        }

    async def group(self, suffix):
        result = await self.post(
            "/v1/admin/network/host-groups",
            {
                "code": self.suffix + suffix,
                "title": "گروه " + suffix,
                "is_enabled": True,
            },
        )
        return result

    async def test_dual_transport_reservations_and_concurrent_creation(self):
        node = (await self.node())["node"]
        shadow_options = {
            "protocol": "shadowsocks",
            "listen_address": "0.0.0.0",
        }
        udp_options = {
            "protocol": "hysteria2",
            "listen_address": "0.0.0.0",
            "server_name": "example.com",
            "certificate_path": "/fixture/tls.crt",
            "private_key_path": "/fixture/tls.key",
        }
        shadow = await self.post(
            "/v1/admin/network/configurations",
            {
                "node_id": node["id"],
                "listen_port": 8443,
                "label": "ورودی دو انتقال",
                "options": shadow_options,
            },
        )
        conflicting = await self.client.post(
            "/v1/admin/network/configurations",
            headers=self.headers,
            json={
                "node_id": node["id"],
                "listen_port": 8443,
                "label": "ورودی UDP",
                "options": udp_options,
            },
        )
        self.assertEqual(conflicting.status_code, 409)
        self.assertEqual(shadow["port_network"], "dual")
        await self.post(
            "/v1/admin/network/configurations",
            {
                "node_id": node["id"],
                "listen_port": 10443,
                "label": "ورودی UDP موجود",
                "options": udp_options,
            },
        )
        denied_dual = await self.client.post(
            "/v1/admin/network/configurations",
            headers=self.headers,
            json={
                "node_id": node["id"],
                "listen_port": 10443,
                "label": "ورودی دو انتقال",
                "options": shadow_options,
            },
        )
        self.assertEqual(denied_dual.status_code, 409)
        tcp = await self.inbound(node["id"], port=10443)
        self.assertEqual(tcp["port_network"], "tcp")
        raced = await asyncio.gather(
            self.client.post(
                "/v1/admin/network/configurations",
                headers=self.headers,
                json={
                    "node_id": node["id"],
                    "listen_port": 9443,
                    "label": "ورودی دو انتقال",
                    "options": shadow_options,
                },
            ),
            self.client.post(
                "/v1/admin/network/configurations",
                headers=self.headers,
                json={
                    "node_id": node["id"],
                    "listen_port": 9443,
                    "label": "ورودی UDP",
                    "options": udp_options,
                },
            ),
        )
        self.assertEqual(
            sorted(response.status_code for response in raced), [200, 409]
        )
        async with self.connection.uow() as fresh:
            rows = await fresh.execute(
                select(ConfigurationTable).where(
                    col(ConfigurationTable.node_id) == node["id"],
                    col(ConfigurationTable.listen_port) == 9443,
                )
            )
            self.assertEqual(len(rows.scalars().all()), 1)

    async def test_multiple_cores_inbounds_ports_and_exports(self):
        node = (await self.node())["node"]
        first = await self.inbound(node["id"])
        core = await self.post(
            f"/v1/admin/network/nodes/{node['id']}/cores",
            {"code": "secondary", "label": "هسته دوم", "kind": "xray"},
        )
        second = await self.inbound(node["id"], core["id"], 8443)
        self.assertNotEqual(first["core_id"], second["core_id"])
        duplicate = await self.client.post(
            "/v1/admin/network/configurations",
            headers=self.headers,
            json={
                "node_id": node["id"],
                "core_id": core["id"],
                "listen_port": 443,
                "label": "ورودی تکراری",
                "options": self.options(),
            },
        )
        self.assertEqual(duplicate.status_code, 409)
        other = await self.post(
            "/v1/admin/network/nodes",
            {
                "code": "other_" + self.suffix,
                "label": "نود دیگر",
                "public_host": "other.example.invalid",
                "public_port": 443,
                "protocol": "vless_reality",
            },
        )
        invalid = await self.client.post(
            "/v1/admin/network/configurations",
            headers=self.headers,
            json={
                "node_id": other["node"]["id"],
                "core_id": core["id"],
                "label": "ورودی ناسازگار",
                "options": self.options(),
            },
        )
        self.assertEqual(invalid.status_code, 409)
        _, subscription = await self.paid_subscription()
        await self.post(
            f"/v1/admin/network/configurations/{second['id']}/profiles",
            {"subscription_id": subscription["id"]},
        )
        server = await self.post(
            f"/v1/admin/network/configurations/{second['id']}/server-download"
        )
        self.assertIn('"port": 8443', server["content"])
        paged = await self.get(
            f"/v1/admin/network/nodes/{node['id']}/cores?per_page=1"
        )
        self.assertEqual(paged["meta"]["pager"]["total_items"], 2)
        filtered = await self.get(
            f"/v1/admin/network/configurations?core_id={core['id']}"
        )
        self.assertEqual(
            [row["id"] for row in filtered["data"]], [second["id"]]
        )
        async with self.connection.uow() as fresh:
            rows = await fresh.execute(
                select(ConfigurationTable).where(
                    col(ConfigurationTable.node_id) == node["id"]
                )
            )
            self.assertEqual(len(rows.scalars().all()), 2)

    async def test_paid_feed_group_overrides_snapshot_and_disable(self):
        customer, subscription = await self.paid_subscription()
        registered = await self.node()
        node = registered["node"]
        enabled = await self.client.patch(
            f"/v1/admin/network/nodes/{node['id']}/enabled",
            headers=self.headers,
            json={"enabled": True},
        )
        self.assertEqual(enabled.status_code, 200)
        inbound = await self.inbound(node["id"])
        host = await self.post(
            f"/v1/admin/network/configurations/{inbound['id']}/hosts",
            {
                "label": "هاست اصلی",
                "address": "default.example.invalid",
                "port": 443,
                "is_enabled": True,
            },
        )
        listed_hosts = await self.get(
            f"/v1/admin/network/hosts?configuration_id={inbound['id']}"
            "&q=هاست&per_page=1"
        )
        self.assertEqual(listed_hosts["meta"]["pager"]["total_items"], 1)
        self.assertEqual(listed_hosts["data"][0]["id"], host["id"])
        groups = await asyncio.gather(self.group("alpha"), self.group("beta"))
        path = (
            f"/v1/admin/network/host-groups/{groups[0]['id']}"
            f"/hosts/{host['id']}"
        )
        overrides = {
            "label": "مسیر اول",
            "address": "alpha.example.invalid",
            "port": 8443,
            "is_enabled": True,
            "sort_order": 0,
        }
        first = await self.put(path, overrides)
        replay = await self.put(path, overrides)
        self.assertEqual(first["id"], replay["id"])
        await self.put(
            f"/v1/admin/network/host-groups/{groups[1]['id']}/hosts/{host['id']}",
            {**overrides, "address": "beta.example.invalid"},
        )
        patched = await self.client.patch(
            f"/v1/admin/plans/{subscription['plan_id']}",
            headers=self.headers,
            json={"group_id": groups[0]["id"]},
        )
        self.assertEqual(patched.status_code, 200)
        grouped = await self.post(
            "/v1/admin/subscriptions",
            {
                "customer_id": customer["id"],
                "plan_id": subscription["plan_id"],
                "purchase_key": "grouped_" + self.suffix,
            },
        )
        changed = await self.client.patch(
            f"/v1/admin/plans/{subscription['plan_id']}",
            headers=self.headers,
            json={"group_id": groups[1]["id"]},
        )
        self.assertEqual(changed.status_code, 200)
        await self.post(
            f"/v1/admin/network/configurations/{inbound['id']}/profiles",
            {"subscription_id": grouped["id"]},
        )
        request = (
            await self.get(
                f"/v1/admin/provisioning?subscription_id={grouped['id']}"
            )
        )["data"][0]
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        tasks = (
            await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
        )["data"]
        self.assertEqual(len(tasks), 1)
        agent_headers = {"X-Papilio-Node-Key": registered["agent_key"]}
        claim = await self.client.post(
            f"/v1/nodes/{node['code']}/provisioning/{tasks[0]['id']}/claim",
            headers=agent_headers,
        )
        self.assertEqual(claim.status_code, 200)
        # The node acknowledgement is a controlled external boundary.
        acknowledged = await self.client.post(
            f"/v1/nodes/{node['code']}/provisioning/{tasks[0]['id']}/acknowledge",
            headers=agent_headers,
            json={
                "claim_token": claim.json()["data"]["claim_token"],
                "outcome": "applied",
            },
        )
        self.assertEqual(acknowledged.status_code, 200)
        await self.post(
            f"/v1/admin/network/configurations/{inbound['id']}/hosts",
            {
                "label": "هاست خارج از گروه",
                "address": "unassigned.example.invalid",
                "port": 443,
                "is_enabled": True,
            },
        )
        self.settings.operations.configuration_export_max_profiles = 1
        private = await self.post(
            f"/v1/admin/network/configurations/subscriptions/{grouped['id']}/link"
        )
        feed_path = "/s/" + private["url"].rsplit("/", 1)[1]
        response = await self.client.get(feed_path)
        self.assertEqual(response.status_code, 200)
        feed = base64.b64decode(response.text).decode()
        self.assertIn("@alpha.example.invalid:8443", feed)
        self.assertNotIn("beta.example.invalid", feed)
        async with self.connection.uow() as fresh:
            rows = await fresh.execute(
                select(SubscriptionTable).where(
                    col(SubscriptionTable.id) == grouped["id"]
                )
            )
            persisted = rows.scalar_one()
            self.assertEqual(persisted.group_id, groups[0]["id"])
        invalid = await self.client.put(
            path,
            headers=self.headers,
            json={
                "server_name": "wrong.example.com",
                "is_enabled": True,
                "sort_order": 0,
            },
        )
        self.assertEqual(invalid.status_code, 409)
        self.assertEqual(
            (await self.get(path))["data"]["membership"]["address"],
            "alpha.example.invalid",
        )
        disabled = await self.put(path, {"is_enabled": False, "sort_order": 0})
        self.assertIsNone(disabled["address"])
        self.assertEqual((await self.client.get(feed_path)).status_code, 404)
        self.assertEqual(
            (
                await self.get(
                    f"/v1/admin/network/host-groups/{groups[0]['id']}/hosts?per_page=1"
                )
            )["meta"]["pager"]["total_items"],
            1,
        )
        self.assertEqual(
            (await self.client.delete(path, headers=self.headers)).status_code,
            204,
        )
        self.assertIsNone((await self.get(path))["data"]["membership"])

    async def test_preferences_bot_policy_history_stale_and_concurrent_edit(
        self,
    ):
        initial = (await self.get("/v1/admin/settings"))["data"]
        values = {
            **initial["values"],
            "brand_title": "پنل آزمون",
            "payment_instructions": "پس از بررسی",
            "support_handle": "@fixture_support",
            "topup_options_rial": [12345, 200000],
            "max_plan_duration_days": 14,
        }
        saved = await self.put(
            "/v1/admin/settings",
            {"expected_revision": initial["revision"], "values": values},
        )
        self.assertEqual(
            (await self.get("/v1/admin/branding"))["data"]["brand_title"],
            values["brand_title"],
        )
        bot = await self.client.post(
            "/v1/bot/home",
            headers={
                "X-Papilio-Bot-Key": self.settings.security.bot_service_key
            },
            json={
                "telegram_id": int(self.suffix, 16),
                "display_name": "مشتری آزمون",
            },
        )
        self.assertEqual(bot.status_code, 200)
        self.assertEqual(
            bot.json()["data"]["topup_options_rial"], [12345, 200000]
        )
        rejected = await self.client.post(
            "/v1/admin/plans",
            headers=self.headers,
            json={
                "code": "policy_" + self.suffix,
                "title": "پلن بیش از سقف",
                "quota_bytes": 1000,
                "duration_days": 15,
                "price_rial": 100,
            },
        )
        self.assertNotEqual(rejected.status_code, 200)
        stale = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": initial["revision"],
                "values": initial["values"],
            },
        )
        self.assertEqual(stale.status_code, 409)
        concurrent = await asyncio.gather(
            self.client.put(
                "/v1/admin/settings",
                headers=self.headers,
                json={
                    "expected_revision": saved["revision"],
                    "values": values,
                },
            ),
            self.client.put(
                "/v1/admin/settings",
                headers=self.headers,
                json={
                    "expected_revision": saved["revision"],
                    "values": values,
                },
            ),
        )
        self.assertEqual(
            sorted(response.status_code for response in concurrent), [200, 409]
        )
        current = (await self.get("/v1/admin/settings"))["data"]
        history = await self.get("/v1/admin/settings/history?per_page=1")
        self.assertEqual(history["data"][0]["revision"], current["revision"])
        self.assertTrue(history["data"][0]["created_at"].endswith("Z"))
        await self.put(
            "/v1/admin/settings",
            {
                "expected_revision": current["revision"],
                "values": initial["values"],
            },
        )

    async def test_read_only_authorization(self):
        node = (await self.node())["node"]
        hashed = await Passwords(self.settings).hash("readonly-password")
        async with self.connection.uow() as unit:
            async with transaction(unit):
                repo = StaffRepository(unit)
                staff = await repo.create(
                    StaffModel(
                        username="foundation_reader_" + self.suffix,
                        password_hash=hashed,
                        is_active=True,
                    )
                )
                await repo.add_grant(staff.id, "network:read")
                await repo.add_grant(staff.id, "settings:read")
        login = await self.client.post(
            "/v1/admin/auth/login",
            headers={"Origin": self.settings.public.admin_origin},
            json={
                "username": "foundation_reader_" + self.suffix,
                "password": "readonly-password",
            },
        )
        self.assertEqual(login.status_code, 200)
        headers = {
            "Origin": self.settings.public.admin_origin,
            "X-CSRF-Token": login.json()["csrf_token"],
        }
        self.assertEqual(
            (
                await self.client.get(
                    f"/v1/admin/network/nodes/{node['id']}/cores"
                )
            ).status_code,
            200,
        )
        current = (await self.get("/v1/admin/settings"))["data"]
        write = await self.client.put(
            "/v1/admin/settings",
            headers=headers,
            json={
                "expected_revision": current["revision"],
                "values": current["values"],
            },
        )
        self.assertEqual(write.status_code, 403)
        group = await self.client.post(
            "/v1/admin/network/host-groups",
            headers=headers,
            json={"code": "denied", "title": "گروه ممنوع", "is_enabled": True},
        )
        self.assertEqual(group.status_code, 403)

    async def test_native_worker_reads_saved_business_thresholds(self):
        from datetime import UTC, datetime, timedelta

        from src.modules.billing.wallet.infra.tables import TopupTable
        from tests.scheduler_runtime import exercise_native_schedulers

        initial = (await self.get("/v1/admin/settings"))["data"]
        values = {
            **initial["values"],
            "node_health_stale_seconds": 1,
            "payment_stale_hours": 1,
        }
        await self.put(
            "/v1/admin/settings",
            {"expected_revision": initial["revision"], "values": values},
        )
        try:
            customer, subscription = await self.paid_subscription(
                auto_renew=True
            )
            topup = await self.post(
                "/v1/admin/payments/topups",
                {"customer_id": customer["id"], "amount_rial": 123456},
            )
            registered = await self.node()
            node = registered["node"]
            enabled = await self.client.patch(
                f"/v1/admin/network/nodes/{node['id']}/enabled",
                headers=self.headers,
                json={"enabled": True},
            )
            self.assertEqual(enabled.status_code, 200)
            now = datetime.now(UTC)

            async def report(index):
                response = await self.client.post(
                    f"/v1/nodes/{node['code']}/probes",
                    headers={"X-Papilio-Node-Key": registered["agent_key"]},
                    json={
                        "event_id": self.suffix + str(index),
                        "client_network": "fixture-network",
                        "success": True,
                        "latency_ms": 30,
                        "sampled_at": (now - timedelta(minutes=2)).isoformat(),
                    },
                )
                self.assertEqual(response.status_code, 200)

            await asyncio.gather(*(report(index) for index in range(3)))
            async with self.connection.uow() as unit:
                async with transaction(unit):
                    await unit.execute(
                        update(SubscriptionTable)
                        .where(col(SubscriptionTable.id) == subscription["id"])
                        .values(
                            status="active",
                            expires_at=now.replace(tzinfo=None)
                            - timedelta(seconds=1),
                        )
                    )
                    await unit.execute(
                        update(TopupTable)
                        .where(col(TopupTable.id) == topup["id"])
                        .values(
                            created_at=now.replace(tzinfo=None)
                            - timedelta(hours=2)
                        )
                    )
            seen = await asyncio.to_thread(
                exercise_native_schedulers,
                self.raw,
                topup["id"],
                node["id"],
                subscription["id"],
            )
            self.assertEqual(seen, ("stale", "stale", 1))
        finally:
            current = (await self.get("/v1/admin/settings"))["data"]
            await self.put(
                "/v1/admin/settings",
                {
                    "expected_revision": current["revision"],
                    "values": initial["values"],
                },
            )
