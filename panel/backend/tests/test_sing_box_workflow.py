import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from sqlalchemy import text

from tests.test_foundations_workflow import FoundationsWorkflowTest
from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowTest,
)


class SingBoxWorkflowTest(
    StaffAdministrationWorkflowTest, FoundationsWorkflowTest
):
    async def test_core_owned_exports_claims_activation_and_recovery(self):
        registered = await self.node()
        node = registered["node"]
        enabled = await self.client.patch(
            f"/v1/admin/network/nodes/{node['id']}/enabled",
            headers=self.headers,
            json={"enabled": True},
        )
        self.assertEqual(enabled.status_code, 200)
        core = await self.post(
            f"/v1/admin/network/nodes/{node['id']}/cores",
            {
                "code": "sing_" + self.suffix,
                "label": "هسته منتخب",
                "kind": "sing_box",
            },
        )
        self.assertEqual(
            set(core["supported_protocols"]),
            {
                "vless_reality",
                "vless_tls",
                "vmess_tls",
                "trojan_tls",
                "shadowsocks",
                "hysteria2",
            },
        )
        core_read = await self.get(f"/v1/admin/network/cores/{core['id']}")
        self.assertEqual(core_read["data"], core)
        options = [self.options()]
        options.extend(
            {
                "protocol": protocol,
                "listen_address": "0.0.0.0",
                "server_name": "tls.example.invalid",
                "certificate_path": "/configured/tls.crt",
                "private_key_path": "/configured/tls.key",
                "transport": transport,
                "transport_path": "/configured-ws"
                if transport == "ws"
                else "configured-grpc"
                if transport == "grpc"
                else None,
            }
            for protocol, transport in [
                ("vless_tls", "tcp"),
                ("vless_tls", "ws"),
                ("vless_tls", "grpc"),
                ("vmess_tls", "ws"),
                ("trojan_tls", "grpc"),
            ]
        )
        options.extend(
            [
                {"protocol": "shadowsocks", "listen_address": "0.0.0.0"},
                {
                    "protocol": "hysteria2",
                    "listen_address": "0.0.0.0",
                    "server_name": "hy.example.invalid",
                    "certificate_path": "/configured/hy.crt",
                    "private_key_path": "/configured/hy.key",
                },
            ]
        )
        inbounds = await asyncio.gather(
            *(
                self.post(
                    "/v1/admin/network/configurations",
                    {
                        "node_id": node["id"],
                        "core_id": core["id"],
                        "listen_port": 6200 + index,
                        "label": "ورودی " + str(index),
                        "options": value,
                    },
                )
                for index, value in enumerate(options)
            )
        )
        customer, subscription = await self.paid_subscription()
        sid = subscription["id"]
        shadow = next(
            row for row in inbounds if row["protocol"] == "shadowsocks"
        )
        empty = await self.client.post(
            f"/v1/admin/network/configurations/{shadow['id']}/server-download",
            headers=self.headers,
        )
        self.assertEqual(empty.status_code, 409)
        profiles = await asyncio.gather(
            *(
                self.post(
                    f"/v1/admin/network/configurations/{row['id']}/profiles",
                    {"subscription_id": sid},
                )
                for row in inbounds
            )
        )
        request = (
            await self.get(f"/v1/admin/provisioning?subscription_id={sid}")
        )["data"][0]
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        tasks = (
            await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
        )["data"]
        self.assertEqual(len(tasks), len(inbounds))
        claims = await asyncio.gather(
            *(
                self.client.post(
                    f"/v1/nodes/{node['code']}/provisioning/{task['id']}/claim",
                    headers={"X-Papilio-Node-Key": registered["agent_key"]},
                )
                for task in tasks
            )
        )
        self.assertTrue(
            all(response.status_code == 200 for response in claims)
        )
        by_configuration = {
            response.json()["data"]["configuration_id"]: response.json()[
                "data"
            ]
            for response in claims
        }
        self.assertTrue(
            all(
                value["core_kind"] == "sing_box"
                and value["core_id"] == core["id"]
                for value in by_configuration.values()
            )
        )
        exports = await asyncio.gather(
            *(
                self.post(
                    f"/v1/admin/network/configurations/{row['id']}/server-download"
                )
                for row in inbounds
            )
        )
        downloads = await asyncio.gather(
            *(
                self.post(
                    f"/v1/admin/network/configurations/profiles/{profile['id']}/client-download"
                )
                for profile in profiles
            )
        )
        for inbound, option, exported, download in zip(
            inbounds, options, exports, downloads, strict=True
        ):
            claim = by_configuration[inbound["id"]]
            credentials = claim["credentials"]
            generated = json.loads(exported["content"])
            self.assertNotIn("streamSettings", exported["content"])
            self.assertIn("sing-box", exported["filename"])
            server = generated["inbounds"][0]
            self.assertEqual(server["listen_port"], inbound["listen_port"])
            self.assertEqual(server["listen"], option["listen_address"])
            user = server["users"][0]
            self.assertEqual(user["name"], credentials["identity"])
            if option["protocol"] == "vless_reality":
                self.assertEqual(
                    server["tls"]["reality"]["private_key"],
                    claim["settings"]["private_key"],
                )
                self.assertEqual(
                    server["tls"]["reality"]["handshake"]["server_port"],
                    option["target_port"],
                )
                self.assertEqual(user["flow"], "xtls-rprx-vision")
            elif option["protocol"] == "hysteria2":
                authentication = (
                    credentials["identity"] + ":" + credentials["password"]
                )
                self.assertEqual(user["password"], authentication)
                self.assertEqual(
                    unquote(
                        urlsplit(download["content"]).netloc.split("@", 1)[0]
                    ),
                    authentication,
                )
            elif option["protocol"] == "shadowsocks":
                self.assertEqual(
                    server["password"], claim["settings"]["server_password"]
                )
                self.assertEqual(user["password"], credentials["password"])
                self.assertNotIn("network", server)
            else:
                self.assertEqual(
                    server["tls"]["certificate_path"],
                    option["certificate_path"],
                )
                self.assertEqual(
                    server["tls"]["key_path"], option["private_key_path"]
                )
                if option["transport"] == "tcp":
                    self.assertNotIn("transport", server)
                else:
                    field = (
                        "path"
                        if option["transport"] == "ws"
                        else "service_name"
                    )
                    self.assertEqual(
                        server["transport"][field], option["transport_path"]
                    )
        acknowledged = await asyncio.gather(
            *(
                self.client.post(
                    f"/v1/nodes/{node['code']}/provisioning/{claim['task_id']}/acknowledge",
                    headers={"X-Papilio-Node-Key": registered["agent_key"]},
                    json={
                        "claim_token": claim["claim_token"],
                        "outcome": "applied",
                    },
                )
                for claim in by_configuration.values()
            )
        )
        self.assertTrue(
            all(response.status_code == 200 for response in acknowledged)
        )
        link = await self.post(
            f"/v1/admin/network/configurations/subscriptions/{sid}/link"
        )
        feed = await self.client.get(urlsplit(link["url"]).path)
        self.assertEqual(feed.status_code, 200)
        self.assertEqual(
            len(base64.b64decode(feed.text).decode().splitlines()),
            len(inbounds),
        )
        async with self.connection.uow() as unit:
            facts = (
                await unit.execute(
                    text(
                        "SELECT status,price_rial FROM tbl_subscriptions "
                        "WHERE id=:id"
                    ),
                    {"id": sid},
                )
            ).one()
            self.assertEqual(tuple(facts), ("active", 100000))
            await unit.execute(
                text(
                    "UPDATE tbl_subscriptions SET expires_at=:expiry "
                    "WHERE id=:id"
                ),
                {
                    "expiry": datetime.now(UTC).replace(tzinfo=None)
                    - timedelta(seconds=1),
                    "id": sid,
                },
            )
            await unit.commit()
        expired = await self.post(
            f"/v1/admin/network/configurations/{inbounds[0]['id']}/server-download"
        )
        self.assertEqual(
            json.loads(expired["content"])["inbounds"][0]["users"], []
        )

    async def test_mismatches_socket_rollback_capacity_and_scoped_exports(
        self,
    ):
        node = (await self.node())["node"]
        core = await self.post(
            f"/v1/admin/network/nodes/{node['id']}/cores",
            {
                "code": "sing_" + self.suffix,
                "label": "هسته",
                "kind": "sing_box",
            },
        )
        invalid = await self.client.post(
            "/v1/admin/network/configurations",
            headers=self.headers,
            json={
                "node_id": node["id"],
                "core_id": core["id"],
                "listen_port": 6400,
                "label": "ناسازگار",
                "options": {
                    "protocol": "wireguard",
                    "server_address": "10.8.0.1/29",
                    "client_subnet": "10.8.0.0/29",
                    "allowed_ips": ["0.0.0.0/0"],
                    "dns": ["1.1.1.1"],
                },
            },
        )
        self.assertEqual(invalid.status_code, 409)
        configured = await self.inbound(node["id"], core["id"], port=6400)
        customer, subscription = await self.paid_subscription()
        await self.post(
            f"/v1/admin/network/configurations/{configured['id']}/profiles",
            {"subscription_id": subscription["id"]},
        )
        second = await self.post(
            "/v1/admin/subscriptions",
            {
                "customer_id": customer["id"],
                "plan_id": subscription["plan_id"],
                "purchase_key": uuid4().hex,
            },
        )
        await self.post(
            f"/v1/admin/network/configurations/{configured['id']}/profiles",
            {"subscription_id": second["id"]},
        )
        self.settings.operations.configuration_export_max_profiles = 1
        path = (
            f"/v1/admin/network/configurations/{configured['id']}"
            "/server-download"
        )
        self.assertEqual(
            (await self.client.post(path, headers=self.headers)).status_code,
            409,
        )
        self.settings.operations.configuration_export_max_profiles = 100
        self.assertEqual(
            (await self.client.post(path, headers=self.headers)).status_code,
            200,
        )
        staff = await self.post(
            "/v1/admin/staff",
            {
                "username": "reader_" + self.suffix,
                "password": "readonly888",
                "is_active": True,
                "scopes": ["network:read"],
            },
        )
        reader, headers = await self.login_staff(
            staff["username"], "readonly888"
        )
        try:
            self.assertEqual(
                (
                    await reader.get(f"/v1/admin/network/cores/{core['id']}")
                ).status_code,
                200,
            )
            denied = await reader.post(path, headers=headers)
            self.assertEqual(denied.status_code, 403)
        finally:
            await reader.aclose()
