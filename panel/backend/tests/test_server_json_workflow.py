import asyncio
import json

from tests.test_fulfillment_workflow import FulfillmentWorkflowFixture
from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowTest,
)


class ServerJsonWorkflowTest(
    StaffAdministrationWorkflowTest, FulfillmentWorkflowFixture
):
    async def private_get(self, path):
        response = await self.client.get(path, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def setup_json(self):
        subscription, request, nodes, purchase = await self.setup_sale(
            protocols=("vless_reality",)
        )
        configuration = (await self.get("/v1/admin/network/configurations"))[
            "data"
        ][0]
        self.base = f"/v1/admin/network/configurations/{configuration['id']}"
        return subscription, request, nodes, purchase

    async def write(self, document, revision=None):
        if revision is None:
            revision = (await self.private_get(self.base + "/server-json"))[
                "data"
            ]["revision"]
        response = await self.client.put(
            self.base + "/server-json",
            headers=self.headers,
            json={
                "expected_revision": revision,
                "reason": "native JSON workflow",
                "document": document,
            },
        )
        return response

    async def test_managed_history_restore_export_and_native_claim(self):
        _, request, nodes, _ = await self.setup_json()
        document = {
            "mode": "managed",
            "source": json.dumps(
                {
                    "inbounds": [{"$papilio": "managed"}],
                    "dns": {"servers": ["9.9.9.9"]},
                    "routing": {"domainStrategy": "IPIfNonMatch"},
                    "outbounds": [{"protocol": "freedom", "tag": "custom"}],
                }
            ),
        }
        saved = await self.write(document)
        self.assertEqual(saved.status_code, 200, saved.text)
        state = (await self.private_get(self.base + "/server-json"))["data"]
        detail = (await self.get(self.base))["data"]
        # Existing settings edits retain the server document.
        changed = await self.client.put(
            self.base,
            headers=self.headers,
            json={
                "label": "تغییر تنظیمات",
                "options": detail["options"],
                "expected_revision": detail["revision"],
            },
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(
            (await self.private_get(self.base + "/server-json"))["data"][
                "document"
            ],
            state["document"],
        )
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        tasks = (
            await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
        )["data"]
        node, claim = await self.claim(tasks[0], nodes)
        self.assertEqual(claim["settings"]["server_json"], state["document"])
        exported = await self.post(self.base + "/server-download")
        value = json.loads(exported["content"])
        self.assertEqual(value["dns"]["servers"], ["9.9.9.9"])
        self.assertEqual(value["outbounds"][0]["tag"], "custom")
        self.assertNotEqual(value["inbounds"], [{"$papilio": "managed"}])
        self.assertTrue(value["inbounds"][0]["settings"]["clients"])
        await self.ack(tasks[0], node, claim)
        history = (
            await self.private_get(
                self.base + "/server-json/history?per_page=1"
            )
        )["data"]
        self.assertIsNone(history[0]["document"])
        restore = await self.client.post(
            self.base + f"/server-json/history/{history[0]['id']}/restore",
            headers=self.headers,
            json={
                "expected_revision": changed.json()["data"]["revision"],
                "reason": "restore generated defaults",
            },
        )
        self.assertEqual(restore.status_code, 200, restore.text)
        self.assertIsNone(
            (await self.private_get(self.base + "/server-json"))["data"][
                "document"
            ]
        )
        self.assertEqual(
            (
                await self.private_get(
                    self.base + "/server-json/history?per_page=1"
                )
            )["meta"]["pager"]["total_items"],
            2,
        )
        denied = await self.write({"mode": "experimental", "source": "{}"})
        self.assertEqual(denied.status_code, 409)

    async def test_experimental_is_exportable_but_not_assignable(self):
        subscription, request, _, _ = await self.setup_json()
        document = {
            "mode": "experimental",
            "source": '{"inbounds":[],"routing":{"rules":[]},"outbounds":[]}',
        }
        saved = await self.write(document)
        self.assertEqual(saved.status_code, 200, saved.text)
        exported = await self.post(self.base + "/server-download")
        self.assertEqual(
            json.loads(exported["content"]), json.loads(document["source"])
        )
        denied = await self.client.post(
            self.base + "/profiles",
            headers=self.headers,
            json={"subscription_id": subscription["id"]},
        )
        self.assertEqual(denied.status_code, 409, denied.text)
        bulk = await self.client.post(
            f"/v1/admin/provisioning/{request['id']}/prepare",
            headers=self.headers,
        )
        self.assertEqual(bulk.status_code, 409, bulk.text)
        self.assertEqual((await self.get(self.base + "/profiles"))["data"], [])
        self.assertEqual((await self.write(None)).status_code, 200)
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")

    async def test_invalid_concurrent_and_private_boundaries(self):
        await self.setup_json()
        state = (await self.private_get(self.base + "/server-json"))["data"]
        limit = state["capacity"]["max_document_bytes"]
        invalid = [
            "[]",
            '{"a":1,"a":2}',
            '{"x":NaN}',
            '{"inbounds":[]}',
            '{"inbounds":[{"$papilio":"managed"}],"x":"' + "x" * limit + '"}',
            '{"inbounds":[{"$papilio":"managed"}],"x":'
            + "[" * 40
            + "0"
            + "]" * 40
            + "}",
        ]
        responses = await asyncio.gather(
            *(
                self.write(
                    {"mode": "managed", "source": source}, state["revision"]
                )
                for source in invalid
            )
        )
        self.assertTrue(
            all(response.status_code == 409 for response in responses)
        )
        self.assertEqual(
            (await self.private_get(self.base + "/server-json/history"))[
                "data"
            ],
            [],
        )
        valid = {
            "mode": "managed",
            "source": '{"inbounds":[{"$papilio":"managed"}]}',
        }
        raced = await asyncio.gather(
            self.write(valid, state["revision"]),
            self.write(valid, state["revision"]),
        )
        self.assertEqual(
            sorted(response.status_code for response in raced), [200, 409]
        )
        staff = await self.post(
            "/v1/admin/staff",
            {
                "username": "reader_" + self.suffix,
                "password": "reader888",
                "scopes": ["network:read"],
                "is_active": True,
            },
        )
        client, headers = await self.login_staff(
            staff["username"], "reader888"
        )
        try:
            ordinary = await client.get(self.base)
            self.assertEqual(ordinary.status_code, 200)
            self.assertNotIn("server_json", ordinary.json()["data"])
            self.assertEqual(
                (
                    await client.get(
                        self.base + "/server-json", headers=headers
                    )
                ).status_code,
                403,
            )
            self.assertEqual(
                (
                    await client.get(
                        self.base + "/server-json/history", headers=headers
                    )
                ).status_code,
                403,
            )

        finally:
            await client.aclose()

    async def test_atomic_failure_race_and_populated_migration_guard(self):
        from unittest.mock import patch

        from alembic import command
        from alembic.config import Config

        from src.modules.network.configurations.infra.mysql import (
            ConfigurationRepository,
        )

        subscription, _, _, _ = await self.setup_json()
        original = (await self.private_get(self.base + "/server-json"))["data"]
        managed = {
            "mode": "managed",
            "source": '{"inbounds":[{"$papilio":"managed"}]}',
        }
        # Fault after the real history insert must roll the entire UOW back.
        with patch.object(
            ConfigurationRepository,
            "update_existing",
            side_effect=RuntimeError("owned write fault"),
        ):
            with self.assertRaisesRegex(RuntimeError, "owned write fault"):
                await self.write(managed, original["revision"])
        self.assertEqual(
            (await self.private_get(self.base + "/server-json"))["data"],
            original,
        )
        self.assertEqual(
            (await self.private_get(self.base + "/server-json/history"))[
                "data"
            ],
            [],
        )
        experimental = {"mode": "experimental", "source": "{}"}
        results = await asyncio.gather(
            self.write(experimental),
            self.client.post(
                self.base + "/profiles",
                headers=self.headers,
                json={"subscription_id": subscription["id"]},
            ),
        )
        self.assertEqual(
            sorted(response.status_code for response in results), [200, 409]
        )
        self.assertEqual((await self.write(managed)).status_code, 200)
        migration = Config("alembic.ini")
        assert self.settings.db is not None
        migration.set_main_option("sqlalchemy.url", self.settings.db.dsn)
        with patch.dict("os.environ", {"PAPILIO_CONFIG": "config.yml.sample"}):
            with self.assertRaisesRegex(
                RuntimeError, "configuration revision history"
            ):
                await asyncio.to_thread(
                    command.downgrade, migration, "0037_plan_limits"
                )
        self.assertTrue(
            (await self.private_get(self.base + "/server-json/history"))[
                "data"
            ]
        )

    async def test_sing_box_and_configurable_capacity(self):
        _, request, nodes, _ = await self.setup_json()
        original_base = self.base
        detail = (await self.get(self.base))["data"]
        core = await self.post(
            f"/v1/admin/network/nodes/{detail['node_id']}/cores",
            {
                "code": "json_sing_" + self.suffix,
                "label": "هسته JSON",
                "kind": "sing_box",
            },
        )
        configuration = await self.post(
            "/v1/admin/network/configurations",
            {
                "node_id": detail["node_id"],
                "core_id": core["id"],
                "listen_port": 8443,
                "label": "ورودی JSON",
                "options": detail["options"],
            },
        )
        self.base = f"/v1/admin/network/configurations/{configuration['id']}"
        document = {
            "mode": "managed",
            "source": (
                '{"inbounds":[{"$papilio":"managed"}],'
                '"route":{"final":"custom"},'
                '"outbounds":[{"type":"direct","tag":"custom"}]}'
            ),
        }
        self.assertEqual((await self.write(document)).status_code, 200)
        exported = json.loads(
            (await self.post(self.base + "/server-download"))["content"]
        )
        self.assertEqual(exported["route"]["final"], "custom")
        self.assertEqual(exported["inbounds"][0]["type"], "vless")
        assert self.settings.configuration_json is not None
        large = {
            "mode": "managed",
            "source": json.dumps(
                {"inbounds": [{"$papilio": "managed"}], "notes": "n" * 90000}
            ),
        }
        self.assertEqual((await self.write(large)).status_code, 200)
        self.assertEqual((await self.write(document)).status_code, 200)
        archived = (
            await self.private_get(self.base + "/server-json/history")
        )["data"]
        self.assertTrue(
            any(
                row["document"] and len(row["document"]["source"]) > 90000
                for row in archived
            )
        )
        self.settings.configuration_json.enabled = False
        self.assertEqual((await self.write(document)).status_code, 409)
        self.assertEqual((await self.write(None)).status_code, 200)

        self.settings.configuration_json.enabled = True
        self.base = original_base
        self.assertEqual((await self.write(large)).status_code, 200)
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        tasks = (
            await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
        )["data"]
        _, claim = await self.claim(tasks[0], nodes)
        self.assertGreater(
            len(claim["settings"]["server_json"]["source"]), 90000
        )
