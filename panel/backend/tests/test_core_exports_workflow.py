import hashlib
import json

from tests.test_fulfillment_workflow import FulfillmentWorkflowFixture
from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowTest,
)


class CoreExportsWorkflowTest(
    StaffAdministrationWorkflowTest, FulfillmentWorkflowFixture
):
    async def setup_core(self):
        subscription, request, nodes, _ = await self.setup_sale(
            protocols=("vless_reality",)
        )
        self.core_subscription_id = subscription["id"]
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        first = (await self.get("/v1/admin/network/configurations"))["data"][0]
        first = (
            await self.get(f"/v1/admin/network/configurations/{first['id']}")
        )["data"]
        second = await self.post(
            "/v1/admin/network/configurations",
            {
                "node_id": first["node_id"],
                "core_id": first["core_id"],
                "label": "Second inbound",
                "listen_port": 8443,
                "options": first["options"],
            },
        )
        await self.post(
            f"/v1/admin/network/configurations/{second['id']}/profiles",
            {"subscription_id": subscription["id"]},
        )
        return first, second, nodes

    async def export_core(self, core_id, mode):
        result = await self.client.post(
            f"/v1/admin/network/cores/{core_id}/export",
            headers=self.headers,
            json={"mode": mode},
        )
        return result

    async def test_native_multi_inbound_export_conflict_and_isolated_recovery(
        self,
    ):
        first, second, _ = await self.setup_core()
        response = await self.export_core(first["core_id"], "merged")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        result = response.json()["data"]
        self.assertEqual(result["application_status"], "not_applied")
        artifact = result["artifacts"][0]
        document = json.loads(artifact["content"])
        self.assertEqual(
            {row["port"] for row in document["inbounds"]}, {443, 8443}
        )
        self.assertEqual(len(document["outbounds"]), 1)
        self.assertTrue(
            all(row["settings"]["clients"] for row in document["inbounds"])
        )
        self.assertEqual(
            artifact["sha256"],
            hashlib.sha256(artifact["content"].encode()).hexdigest(),
        )
        self.assertEqual(
            {row["configuration_id"] for row in artifact["configurations"]},
            {first["id"], second["id"]},
        )
        changed = await self.client.put(
            f"/v1/admin/network/configurations/{second['id']}/server-json",
            headers=self.headers,
            json={
                "expected_revision": second["revision"],
                "reason": "Distinct shared DNS",
                "document": {
                    "mode": "managed",
                    "source": json.dumps(
                        {
                            "inbounds": [{"$papilio": "managed"}],
                            "dns": {"servers": ["9.9.9.9"]},
                        }
                    ),
                },
            },
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        conflicting = await self.export_core(first["core_id"], "merged")
        self.assertEqual(conflicting.status_code, 409, conflicting.text)
        self.assertIn("core_export_global_conflict", conflicting.text)
        isolated = await self.export_core(first["core_id"], "isolated")
        self.assertEqual(isolated.status_code, 200, isolated.text)
        artifacts = isolated.json()["data"]["artifacts"]
        self.assertEqual(len(artifacts), 2)
        revised = next(
            row
            for row in artifacts
            if row["configurations"][0]["configuration_id"] == second["id"]
        )
        self.assertEqual(
            revised["configurations"][0]["revision"],
            changed.json()["data"]["revision"],
        )
        self.assertEqual(
            json.loads(revised["content"])["dns"]["servers"], ["9.9.9.9"]
        )
        # An independent committed GET remains an inventory draft.
        self.assertEqual(
            (await self.get(f"/v1/admin/network/cores/{first['core_id']}"))[
                "data"
            ]["application_status"],
            "draft",
        )

    async def test_native_export_capacities_modes_and_csrf(self):
        first, _, _ = await self.setup_core()
        path = f"/v1/admin/network/cores/{first['core_id']}/export"
        denied = await self.client.post(path, json={"mode": "merged"})
        self.assertEqual(denied.status_code, 403)
        invalid = await self.export_core(first["core_id"], "unknown")
        self.assertEqual(invalid.status_code, 422)
        capacity = self.settings.core_exports
        assert capacity is not None
        capacity.max_configurations = 1
        overflow = await self.export_core(first["core_id"], "isolated")
        self.assertEqual(overflow.status_code, 409)
        self.assertIn("core_export_capacity", overflow.text)
        capacity.max_configurations = 128
        capacity.max_profiles = 1
        overflow = await self.export_core(first["core_id"], "isolated")
        self.assertEqual(overflow.status_code, 409)
        capacity.max_profiles = 16384
        capacity.max_output_bytes = 1
        overflow = await self.export_core(first["core_id"], "isolated")
        self.assertEqual(overflow.status_code, 409)
        self.assertIn("core_export_output_capacity", overflow.text)
        capacity.enabled = False
        disabled = await self.export_core(first["core_id"], "isolated")
        self.assertEqual(disabled.status_code, 409)
        self.assertIn("core_export_disabled", disabled.text)

    async def test_native_selected_batch_and_scoped_secret_export(self):
        first, second, _ = await self.setup_core()
        path = "/v1/admin/network/configurations/server-downloads"
        response = await self.client.post(
            path,
            headers=self.headers,
            json={"configuration_ids": [second["id"], first["id"]]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(
            {row["configuration_id"] for row in response.json()["data"]},
            {first["id"], second["id"]},
        )
        duplicate = await self.client.post(
            path,
            headers=self.headers,
            json={"configuration_ids": [first["id"], first["id"]]},
        )
        self.assertEqual(duplicate.status_code, 409)
        invalid = await self.client.post(
            path, headers=self.headers, json={"configuration_ids": []}
        )
        self.assertEqual(invalid.status_code, 422)
        staff = await self.post(
            "/v1/admin/staff",
            {
                "username": "export_reader_" + self.suffix,
                "password": "fixture888",
                "is_active": True,
                "scopes": ["network:read", "network:create"],
            },
        )
        client, headers = await self.login_staff(
            staff["username"], "fixture888"
        )
        try:
            denied_core = await client.post(
                f"/v1/admin/network/cores/{first['core_id']}/export",
                headers=headers,
                json={"mode": "merged"},
            )
            self.assertEqual(denied_core.status_code, 403)
            denied_batch = await client.post(
                path,
                headers=headers,
                json={"configuration_ids": [first["id"]]},
            )
            self.assertEqual(denied_batch.status_code, 403)
        finally:
            await client.aclose()

    async def test_native_exhausted_quota_is_not_exported(self):
        from papilio.infra.db.transaction import transaction
        from sqlalchemy import update
        from sqlmodel import col

        from src.modules.sales.subscriptions.infra.tables import (
            SubscriptionTable,
        )

        first, _, _ = await self.setup_core()
        async with self.connection.uow() as unit:
            async with transaction():
                await unit.execute(
                    update(SubscriptionTable)
                    .where(
                        col(SubscriptionTable.id) == self.core_subscription_id
                    )
                    .values(used_bytes=col(SubscriptionTable.quota_bytes))
                )
        response = await self.export_core(first["core_id"], "merged")
        self.assertEqual(response.status_code, 200, response.text)
        document = json.loads(
            response.json()["data"]["artifacts"][0]["content"]
        )
        self.assertTrue(
            all(not row["settings"]["clients"] for row in document["inbounds"])
        )
        single = await self.post(
            f"/v1/admin/network/configurations/{first['id']}/server-download"
        )
        self.assertEqual(
            json.loads(single["content"])["inbounds"][0]["settings"][
                "clients"
            ],
            [],
        )


class CoreMergedTrafficWorkflowTest(CoreExportsWorkflowTest):
    async def setup_traffic_core(self, runtime, kind, subscription_id):
        import asyncio

        ports = [runtime.port(), runtime.port()]
        registered = await self.post(
            "/v1/admin/network/nodes",
            {
                "code": f"merged_{kind}_{self.suffix}",
                "label": "Owned merged core",
                "public_host": "127.0.0.1",
                "public_port": ports[0],
                "protocol": "vless_reality",
            },
        )
        core = await self.post(
            f"/v1/admin/network/nodes/{registered['node']['id']}/cores",
            {
                "code": "merged",
                "label": "Owned merged core",
                "kind": kind,
            },
        )
        configurations = await asyncio.gather(
            *(
                self.post(
                    "/v1/admin/network/configurations",
                    {
                        "node_id": registered["node"]["id"],
                        "core_id": core["id"],
                        "listen_port": port,
                        "label": "Owned loopback inbound",
                        "options": {
                            "protocol": "vless_reality",
                            "listen_address": "127.0.0.1",
                            "server_name": "localhost",
                            "target_port": runtime.handshake_port,
                        },
                    },
                )
                for port in ports
            )
        )
        profiles = await asyncio.gather(
            *(
                self.post(
                    f"/v1/admin/network/configurations/{configuration['id']}/profiles",
                    {"subscription_id": subscription_id},
                )
                for configuration in configurations
            )
        )
        clients = await asyncio.gather(
            *(
                self.post(
                    f"/v1/admin/network/configurations/profiles/{profile['id']}/client-download"
                )
                for profile in profiles
            )
        )
        response = await self.export_core(core["id"], "merged")
        self.assertEqual(response.status_code, 200, response.text)
        artifact = response.json()["data"]["artifacts"][0]
        return (
            kind,
            artifact["content"],
            [client["content"] for client in clients],
        )

    async def test_native_merged_xray_and_sing_box_real_traffic(self):
        import asyncio
        import os
        import tempfile
        from pathlib import Path

        from tests.real_core_runtime import RealCoreRuntime

        binaries = os.environ.get("PAPILIO_CORE_BIN_DIR")
        if binaries is None:
            self.skipTest("Explicit real-core opt-in is required")
        with tempfile.TemporaryDirectory(
            prefix="papilio-merged-core-"
        ) as directory:
            runtime = await asyncio.to_thread(
                RealCoreRuntime(Path(directory), Path(binaries), 15).__enter__
            )
            try:
                _, subscription = await self.paid_subscription()
                cases = await asyncio.gather(
                    self.setup_traffic_core(
                        runtime, "xray", subscription["id"]
                    ),
                    self.setup_traffic_core(
                        runtime, "sing_box", subscription["id"]
                    ),
                )
                await asyncio.to_thread(self.exercise_merged, runtime, cases)
            finally:
                await asyncio.to_thread(runtime.__exit__, None, None, None)

    @staticmethod
    def exercise_merged(runtime, cases):
        for kind, content, clients in cases:
            for index, client in enumerate(clients):
                runtime.traffic(
                    f"merged-{kind}-{index}",
                    "sing-box" if kind == "sing_box" else kind,
                    content,
                    client,
                )
