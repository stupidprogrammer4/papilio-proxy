import asyncio
import base64
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlmodel import col

from src.modules.network.configurations.infra.tables import ProfileTable
from src.modules.network.ip_limits.infra.tables import IpLimitPolicyTable
from src.modules.network.provisioning.infra.tables import (
    ProvisionRequestTable,
    ProvisionTaskTable,
)
from src.modules.sales.subscriptions.infra.tables import SubscriptionTable
from tests.test_automation_workflow import AutomationWorkflowFixture


class FulfillmentWorkflowFixture(AutomationWorkflowFixture):
    async def setup_sale(
        self,
        *,
        activation="all",
        automatic=True,
        failure_action="hold",
        attempts=3,
        protocols=("vless_reality", "vless_reality"),
        quota_policy=None,
        configuration_options=None,
        quota_bytes: int | None = 1000000000,
        duration_days: int | None = 30,
        renewal_trigger=None,
    ):
        group = await self.post(
            "/v1/admin/network/host-groups",
            {
                "code": "ful_" + self.suffix,
                "title": "تحویل",
                "is_enabled": True,
            },
        )
        nodes = []
        for index, protocol in enumerate(protocols):
            nodes.append(
                {
                    "code": f"ful_{index}_{self.suffix}",
                    "label": "نود تحویل",
                    "public_host": f"node-{index}.example.invalid",
                    "public_port": 443,
                    "protocol": protocol,
                }
            )
        registered = await asyncio.gather(
            *(self.post("/v1/admin/network/nodes", row) for row in nodes)
        )
        await asyncio.gather(
            *(
                self.client.patch(
                    f"/v1/admin/network/nodes/{row['node']['id']}/enabled",
                    headers=self.headers,
                    json={"enabled": True},
                )
                for row in registered
            )
        )
        options = [
            {
                "protocol": "wireguard",
                "server_address": "10.44.0.1/29",
                "client_subnet": "10.44.0.0/29",
                "allowed_ips": ["0.0.0.0/0"],
                "dns": ["1.1.1.1"],
                "listen_address": "0.0.0.0",
            }
            if protocol == "wireguard"
            else {
                "protocol": protocol,
                "listen_address": "0.0.0.0",
                "server_name": "example.com",
                "target_port": 443,
            }
            for protocol in protocols
        ]
        if configuration_options is not None:
            self.assertEqual(len(configuration_options), len(protocols))
            options = configuration_options
        configurations = await asyncio.gather(
            *(
                self.post(
                    "/v1/admin/network/configurations",
                    {
                        "node_id": row["node"]["id"],
                        "label": "ورودی تحویل",
                        "options": option,
                    },
                )
                for row, option in zip(registered, options, strict=True)
            )
        )
        hosts = await asyncio.gather(
            *(
                self.post(
                    f"/v1/admin/network/configurations/{row['id']}/hosts",
                    {
                        "label": f"مسیر {index}",
                        "address": f"host-{index}.example.invalid",
                        "port": 443,
                        "is_enabled": True,
                    },
                )
                for index, row in enumerate(configurations)
            )
        )
        memberships = await asyncio.gather(
            *(
                self.client.put(
                    f"/v1/admin/network/host-groups/{group['id']}/hosts/{host['id']}",
                    headers=self.headers,
                    json={"is_enabled": True, "sort_order": index},
                )
                for index, host in enumerate(hosts)
            )
        )
        self.assertTrue(
            all(response.status_code == 200 for response in memberships)
        )
        policy = {
            **self.raw["fulfillment"]["policy"],
            "activation": activation,
            "automatic": automatic,
            "max_attempts": attempts,
            "failure_action": failure_action,
            "renewal_trigger": renewal_trigger
            or self.raw["fulfillment"]["policy"]["renewal_trigger"],
        }
        plan = await self.post(
            "/v1/admin/plans",
            {
                "code": "ful_" + self.suffix,
                "title": "فروش تحویل",
                "quota_bytes": quota_bytes,
                "duration_days": duration_days,
                "price_rial": 100000,
                "group_id": group["id"],
                "quota_policy": quota_policy,
                "fulfillment": policy,
                "ip_limit": {
                    "enabled": True,
                    "max_ips": 1,
                    "lease_seconds": 60,
                    "ban_seconds": 30,
                    "mode": "reject_new",
                },
            },
        )
        active = await self.client.patch(
            f"/v1/admin/plans/{plan['id']}/active",
            headers=self.headers,
            json={"is_active": True},
        )
        self.assertEqual(active.status_code, 200)
        customer = await self.post(
            "/v1/admin/customers",
            {
                "display_name": "مشتری تحویل",
                "telegram_id": int(self.suffix, 16),
            },
        )
        topup = await self.post(
            "/v1/admin/payments/topups",
            {"customer_id": customer["id"], "amount_rial": 300000},
        )
        await self.post(
            f"/v1/admin/payments/topups/{topup['id']}/approve",
            {"expected_revision": 1, "bank_reference": "ful_" + self.suffix},
        )
        purchase_body = {
            "customer_id": customer["id"],
            "plan_id": plan["id"],
            "purchase_key": "ful_" + self.suffix,
            "auto_renew": True,
        }
        subscription = await self.post(
            "/v1/admin/subscriptions", purchase_body
        )
        requests = await self.get(
            f"/v1/admin/provisioning?subscription_id={subscription['id']}"
        )
        self.assertEqual(requests["meta"]["pager"]["total_items"], 1)
        self.assertNotIn("policy_json", requests["data"][0])
        return subscription, requests["data"][0], registered, purchase_body

    async def claim(self, task, registered):
        node = next(
            row for row in registered if row["node"]["id"] == task["node_id"]
        )
        response = await self.client.post(
            f"/v1/nodes/{node['node']['code']}/provisioning/{task['id']}/claim",
            headers={"X-Papilio-Node-Key": node["agent_key"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        return node, response.json()["data"]

    async def ack(self, task, node, claim, outcome="applied", error_code=None):
        response = await self.client.post(
            f"/v1/nodes/{node['node']['code']}/provisioning/{task['id']}/acknowledge",
            headers={"X-Papilio-Node-Key": node["agent_key"]},
            json={
                "claim_token": claim["claim_token"],
                "outcome": outcome,
                "error_code": error_code,
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]


class FulfillmentWorkflowTest(FulfillmentWorkflowFixture):
    async def test_all_targets_activation_delivery_replays_and_owned_leases(
        self,
    ):
        subscription, request, nodes, purchase = await self.setup_sale()
        sid = subscription["id"]
        self.assertEqual(subscription["status"], "pending_provision")
        self.assertTrue(subscription["provisioning_managed"])
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        repeated = await self.post("/v1/admin/subscriptions", purchase)
        self.assertEqual(repeated["id"], sid)
        tasks = (
            await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
        )["data"]
        self.assertEqual(len(tasks), 2)
        self.assertNotIn("encrypted_payload", tasks[0])
        claims = await asyncio.gather(
            *(self.claim(task, nodes) for task in tasks)
        )
        competing = await self.client.post(
            f"/v1/nodes/{claims[0][0]['node']['code']}/provisioning/{tasks[0]['id']}/claim",
            headers={"X-Papilio-Node-Key": claims[0][0]["agent_key"]},
        )
        self.assertEqual(competing.status_code, 409)
        wrong_node = await self.client.post(
            f"/v1/nodes/{claims[1][0]['node']['code']}/provisioning/{tasks[0]['id']}/acknowledge",
            headers={"X-Papilio-Node-Key": claims[1][0]["agent_key"]},
            json={
                "claim_token": claims[0][1]["claim_token"],
                "outcome": "applied",
            },
        )
        self.assertEqual(wrong_node.status_code, 404)
        await self.ack(tasks[0], *claims[0])
        before = (await self.get(f"/v1/admin/subscriptions/{sid}"))["data"]
        self.assertEqual(before["status"], "pending_provision")
        await self.ack(tasks[1], *claims[1])
        after = (await self.get(f"/v1/admin/subscriptions/{sid}"))["data"]
        self.assertEqual(after["status"], "active")
        self.assertIsNotNone(after["activated_at"])
        duration = datetime.fromisoformat(
            after["expires_at"]
        ) - datetime.fromisoformat(after["activated_at"])
        self.assertEqual(duration, timedelta(days=30))
        duplicate = await self.ack(tasks[0], *claims[0])
        self.assertEqual(duplicate["state"], "applied")
        stable = (await self.get(f"/v1/admin/subscriptions/{sid}"))["data"]
        self.assertEqual(stable["expires_at"], after["expires_at"])
        url = (
            await self.post(
                f"/v1/admin/network/configurations/subscriptions/{sid}/link"
            )
        )["url"]
        feed = await self.client.get("/s/" + url.rsplit("/", 1)[-1])
        self.assertEqual(feed.status_code, 200)
        content = base64.b64decode(feed.text).decode()
        self.assertIn("host-0.example.invalid", content)
        self.assertIn("host-1.example.invalid", content)
        async with self.connection.uow() as unit:
            policy = await unit.execute(
                select(IpLimitPolicyTable).where(
                    col(IpLimitPolicyTable.subscription_id) == sid
                )
            )
            self.assertEqual(policy.scalar_one().max_ips, 1)
            saved = await unit.execute(
                select(ProvisionTaskTable).where(
                    col(ProvisionTaskTable.id) == tasks[0]["id"]
                )
            )
            self.assertNotIn(
                claims[0][1]["credentials"]["identity"],
                saved.scalar_one().encrypted_payload,
            )
        balance = (
            await self.get(
                f"/v1/admin/payments/wallets/{subscription['customer_id']}"
            )
        )["data"]["balance_rial"]
        self.assertEqual(balance, 200000)

    async def test_partial_activation_publishes_only_acknowledged_profiles(
        self,
    ):
        subscription, request, nodes, _ = await self.setup_sale(
            activation="any"
        )
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        tasks = (
            await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
        )["data"]
        claim = await self.claim(tasks[0], nodes)
        await self.ack(tasks[0], *claim)
        after = (
            await self.get(f"/v1/admin/subscriptions/{subscription['id']}")
        )["data"]
        self.assertEqual(after["status"], "active")
        url = (
            await self.post(
                f"/v1/admin/network/configurations/subscriptions/{subscription['id']}/link"
            )
        )["url"]
        feed = await self.client.get("/s/" + url.rsplit("/", 1)[-1])
        content = base64.b64decode(feed.text).decode()
        self.assertIn("host-0.example.invalid", content)
        self.assertNotIn("host-1.example.invalid", content)

    async def test_refund_waits_for_revocation_even_on_disabled_nodes(self):
        subscription, request, nodes, _ = await self.setup_sale(
            failure_action="refund_wallet", attempts=1
        )
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        tasks = (
            await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
        )["data"]
        claims = await asyncio.gather(
            *(self.claim(task, nodes) for task in tasks)
        )
        await self.ack(tasks[0], *claims[0])
        await self.ack(
            tasks[1],
            *claims[1],
            outcome="failed",
            error_code="adapter_unavailable",
        )
        state = (
            await self.get(
                f"/v1/admin/provisioning?subscription_id={subscription['id']}"
            )
        )["data"][0]
        self.assertEqual(state["state"], "revoking")
        balance_path = (
            f"/v1/admin/payments/wallets/{subscription['customer_id']}"
        )
        self.assertEqual(
            (await self.get(balance_path))["data"]["balance_rial"], 200000
        )
        # An uncertain apply result must be revoked before credit is returned.
        stale_ack = await self.client.post(
            f"/v1/nodes/{claims[0][0]['node']['code']}/provisioning/{tasks[0]['id']}/acknowledge",
            headers={"X-Papilio-Node-Key": claims[0][0]["agent_key"]},
            json={
                "claim_token": claims[0][1]["claim_token"],
                "outcome": "applied",
            },
        )
        self.assertEqual(stale_ack.status_code, 409)
        disabled = await self.client.patch(
            f"/v1/admin/network/nodes/{nodes[0]['node']['id']}/enabled",
            headers=self.headers,
            json={"enabled": False},
        )
        self.assertEqual(disabled.status_code, 200)
        revokes = await asyncio.gather(
            *(self.claim(task, nodes) for task in tasks)
        )
        await self.ack(tasks[0], *revokes[0], outcome="revoked")
        self.assertEqual(
            (await self.get(balance_path))["data"]["balance_rial"], 200000
        )
        await self.ack(tasks[1], *revokes[1], outcome="revoked")
        await self.ack(tasks[1], *revokes[1], outcome="revoked")
        self.assertEqual(
            (await self.get(balance_path))["data"]["balance_rial"], 300000
        )
        failed = (
            await self.get(f"/v1/admin/subscriptions/{subscription['id']}")
        )["data"]
        self.assertEqual(failed["status"], "failed")
        ledger = await self.get(
            balance_path + "/entries?reason=provision_refund"
        )
        self.assertEqual(ledger["meta"]["pager"]["total_items"], 1)

    async def test_manual_preparation_wireguard_pool_and_claim_replacement(
        self,
    ):
        subscription, request, nodes, _ = await self.setup_sale(
            automatic=False, protocols=("wireguard",)
        )
        from src.modules.network.provisioning.interfaces import (
            IProvisioningCommand,
        )

        async with self.app.state.dishka_container() as scope:
            command = await scope.get(IProvisioningCommand)
            skipped = await command.prepare(request["id"])
            self.assertEqual(skipped.state, "queued")
        tasks = await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
        self.assertEqual(tasks["data"], [])
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        task = (
            await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
        )["data"][0]
        first = await self.claim(task, nodes)
        self.assertEqual(first[1]["client_address"], "10.44.0.2/32")
        async with self.connection.uow() as unit:
            await unit.execute(
                update(ProvisionTaskTable)
                .where(col(ProvisionTaskTable.id) == task["id"])
                .values(
                    claim_until=datetime.now(UTC).replace(tzinfo=None)
                    - timedelta(seconds=1)
                )
            )
            await unit.commit()
        second = await self.claim(task, nodes)
        self.assertNotEqual(second[1]["claim_token"], first[1]["claim_token"])
        stale = await self.client.post(
            f"/v1/nodes/{nodes[0]['node']['code']}/provisioning/{task['id']}/acknowledge",
            headers={"X-Papilio-Node-Key": nodes[0]["agent_key"]},
            json={
                "claim_token": first[1]["claim_token"],
                "outcome": "applied",
            },
        )
        self.assertEqual(stale.status_code, 409)
        await self.ack(task, *second)
        async with self.connection.uow() as unit:
            profiles = await unit.execute(
                select(ProfileTable).where(
                    col(ProfileTable.subscription_id) == subscription["id"]
                )
            )
            self.assertEqual(profiles.scalar_one().applied_generation, 0)

    async def test_native_scheduler_prepares_committed_work(self):
        subscription, request, _, _ = await self.setup_sale()
        from tests.scheduler_runtime import exercise_native_provisioning

        observed = await asyncio.to_thread(
            exercise_native_provisioning, self.raw, request["id"]
        )
        self.assertEqual(observed, ("dispatching", 2))
        async with self.connection.uow() as unit:
            saved = await unit.execute(
                select(ProvisionRequestTable).where(
                    col(ProvisionRequestTable.id) == request["id"]
                )
            )
            self.assertEqual(saved.scalar_one().state, "dispatching")
        # The worker prepares work; the external adapter has not applied it.
        current = (
            await self.get(f"/v1/admin/subscriptions/{subscription['id']}")
        )["data"]
        self.assertEqual(current["status"], "pending_provision")

    async def test_inbound_revision_recovery_preserves_charge_and_expiry(
        self,
    ):
        subscription, request, nodes, _ = await self.setup_sale(
            protocols=("vless_reality",)
        )
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        task = (
            await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
        )["data"][0]
        original = await self.claim(task, nodes)
        await self.ack(task, *original)
        before = (
            await self.get(f"/v1/admin/subscriptions/{subscription['id']}")
        )["data"]
        url = (
            await self.post(
                f"/v1/admin/network/configurations/subscriptions/{subscription['id']}/link"
            )
        )["url"]
        token = url.rsplit("/", 1)[-1]
        configuration = (
            await self.get(
                f"/v1/admin/network/configurations/{task['configuration_id']}"
            )
        )["data"]
        changed = await self.client.put(
            f"/v1/admin/network/configurations/{task['configuration_id']}",
            headers=self.headers,
            json={
                "expected_revision": configuration["revision"],
                "label": configuration["label"],
                "options": {
                    **configuration["options"],
                    "server_name": "new.example.com",
                },
            },
        )
        self.assertEqual(changed.status_code, 200)
        unavailable = await self.client.get(f"/s/{token}")
        self.assertEqual(unavailable.status_code, 404)
        stale = await self.client.post(
            f"/v1/nodes/{nodes[0]['node']['code']}/provisioning/{task['id']}/acknowledge",
            headers={"X-Papilio-Node-Key": nodes[0]["agent_key"]},
            json={
                "claim_token": original[1]["claim_token"],
                "outcome": "applied",
            },
        )
        self.assertEqual(stale.status_code, 409)
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        refreshed = await self.claim(task, nodes)
        self.assertEqual(refreshed[1]["configuration_revision"], 2)
        self.assertEqual(
            refreshed[1]["credentials"]["identity"],
            original[1]["credentials"]["identity"],
        )
        await self.ack(task, *refreshed)
        after = (
            await self.get(f"/v1/admin/subscriptions/{subscription['id']}")
        )["data"]
        self.assertEqual(after["expires_at"], before["expires_at"])
        feed = await self.client.get(f"/s/{token}")
        self.assertEqual(feed.status_code, 200)
        self.assertIn(
            "sni=new.example.com", base64.b64decode(feed.text).decode()
        )
        balance = (
            await self.get(
                f"/v1/admin/payments/wallets/{subscription['customer_id']}"
            )
        )["data"]["balance_rial"]
        self.assertEqual(balance, 200000)

    async def test_customer_delivery_pagination_ownership_and_rotation(
        self,
    ):
        subscription, request, nodes, purchase = await self.setup_sale()
        sid = subscription["id"]
        customer = (
            await self.get(
                f"/v1/admin/customers/{subscription['customer_id']}"
            )
        )["data"]
        identity = {
            "telegram_id": customer["telegram_id"],
            "display_name": customer["display_name"],
        }
        bot_headers = {
            "X-Papilio-Bot-Key": self.settings.security.bot_service_key
        }
        before = await self.client.post(
            f"/v1/bot/subscriptions/{sid}/delivery",
            headers=bot_headers,
            json=identity,
        )
        self.assertEqual(before.status_code, 200)
        self.assertIsNone(before.json()["data"]["portal_url"])
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        tasks = (
            await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
        )["data"]
        claims = await asyncio.gather(
            *(self.claim(task, nodes) for task in tasks)
        )
        await asyncio.gather(
            *(
                self.ack(task, *claim)
                for task, claim in zip(tasks, claims, strict=True)
            )
        )
        view = await self.client.post(
            f"/v1/bot/subscriptions/{sid}/delivery",
            headers=bot_headers,
            json=identity,
        )
        self.assertEqual(view.status_code, 200)
        self.assertEqual(view.headers["cache-control"], "no-store")
        token = view.json()["data"]["feed_url"].rsplit("/", 1)[-1]
        first = await self.get(f"/s/{token}/profiles?per_page=1")
        second = await self.get(f"/s/{token}/profiles?page=2&per_page=1")
        self.assertEqual(first["meta"]["pager"]["total_items"], 2)
        self.assertNotEqual(
            first["data"][0]["profile_id"], second["data"][0]["profile_id"]
        )
        profile = first["data"][0]
        downloaded = await self.client.get(
            f"/s/{token}/profiles/{profile['profile_id']}/download?host_id={profile['host_id']}"
        )
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.headers["cache-control"], "no-store")
        self.assertIn(
            "host-0.example.invalid", downloaded.json()["data"]["content"]
        )
        forbidden = await self.client.post(
            f"/v1/bot/subscriptions/{sid}/delivery",
            headers=bot_headers,
            json={**identity, "telegram_id": identity["telegram_id"] + 1},
        )
        self.assertEqual(forbidden.status_code, 404)
        # Another subscription has separate credentials and ownership.
        other = await self.post(
            "/v1/admin/subscriptions",
            {**purchase, "purchase_key": "other_" + self.suffix},
        )
        other_request = (
            await self.get(
                f"/v1/admin/provisioning?subscription_id={other['id']}"
            )
        )["data"][0]
        await self.post(
            f"/v1/admin/provisioning/{other_request['id']}/prepare"
        )
        other_task = (
            await self.get(
                f"/v1/admin/provisioning/{other_request['id']}/tasks"
            )
        )["data"][0]
        cross = await self.client.get(
            f"/s/{token}/profiles/{other_task['profile_id']}/download?host_id={profile['host_id']}"
        )
        self.assertEqual(cross.status_code, 404)
        preferences = (await self.get("/v1/admin/settings"))["data"]
        previous_values = {**preferences["values"]}
        preferences["values"]["customer_link_rotation"] = False
        saved = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": preferences["revision"],
                "values": preferences["values"],
            },
        )
        self.assertEqual(saved.status_code, 200)
        disabled = await self.client.post(
            f"/v1/bot/subscriptions/{sid}/rotate-link",
            headers=bot_headers,
            json=identity,
        )
        self.assertEqual(disabled.status_code, 409)
        preferences = (await self.get("/v1/admin/settings"))["data"]
        preferences["values"]["customer_link_rotation"] = True
        saved = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": preferences["revision"],
                "values": preferences["values"],
            },
        )
        self.assertEqual(saved.status_code, 200)
        rotated = await self.client.post(
            f"/v1/bot/subscriptions/{sid}/rotate-link",
            headers=bot_headers,
            json=identity,
        )
        self.assertEqual(rotated.status_code, 200)
        self.assertNotEqual(
            rotated.json()["data"]["feed_url"], view.json()["data"]["feed_url"]
        )
        old = await self.client.get(f"/s/{token}/status")
        self.assertEqual(old.status_code, 404)
        latest = (await self.get("/v1/admin/settings"))["data"]
        restored = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": latest["revision"],
                "values": previous_values,
            },
        )
        self.assertEqual(restored.status_code, 200)

    async def test_ip_admission_handles_multiple_acknowledged_inbounds(self):
        subscription, request, nodes, _ = await self.setup_sale(
            protocols=("vless_reality",)
        )
        inbound = await self.post(
            "/v1/admin/network/configurations",
            {
                "node_id": nodes[0]["node"]["id"],
                "listen_port": 8443,
                "label": "ورودی دوم",
                "options": {
                    "protocol": "vless_reality",
                    "listen_address": "0.0.0.0",
                    "server_name": "example.com",
                    "target_port": 443,
                },
            },
        )
        host = await self.post(
            f"/v1/admin/network/configurations/{inbound['id']}/hosts",
            {
                "label": "مسیر دوم",
                "address": "second.example.invalid",
                "port": 8443,
                "is_enabled": True,
            },
        )
        membership = await self.client.put(
            f"/v1/admin/network/host-groups/{subscription['group_id']}/hosts/{host['id']}",
            headers=self.headers,
            json={"is_enabled": True, "sort_order": 1},
        )
        self.assertEqual(membership.status_code, 200)
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        tasks = (
            await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
        )["data"]
        self.assertEqual(len(tasks), 2)
        claims = await asyncio.gather(
            *(self.claim(task, nodes) for task in tasks)
        )
        await asyncio.gather(
            *(
                self.ack(task, *claim)
                for task, claim in zip(tasks, claims, strict=True)
            )
        )
        path = f"/v1/nodes/{nodes[0]['node']['code']}/ip-admission"
        headers = {"X-Papilio-Node-Key": nodes[0]["agent_key"]}
        response = await self.client.post(
            path,
            headers=headers,
            json={
                "subscription_id": subscription["id"],
                "source_ip": "203.0.113.9",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["allowed"])
        async with self.connection.uow() as unit:
            await unit.execute(
                update(SubscriptionTable)
                .where(col(SubscriptionTable.id) == subscription["id"])
                .values(used_bytes=subscription["quota_bytes"])
            )
            await unit.commit()
        exhausted = await self.client.post(
            path,
            headers=headers,
            json={
                "subscription_id": subscription["id"],
                "source_ip": "203.0.113.9",
            },
        )
        self.assertEqual(exhausted.status_code, 200)
        self.assertFalse(exhausted.json()["data"]["allowed"])
        self.assertEqual(exhausted.json()["data"]["reason"], "quota_exhausted")
