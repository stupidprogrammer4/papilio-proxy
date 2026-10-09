"""Native paid assignment followed by an isolated API-presence lease probe.

The managed children do NOT acknowledge an installed backend runtime. The stock
runtime is stopped through its actual command/ACK protocol before they start.
This is source-IP lease evidence, never devices or immediate global eviction.
"""

import asyncio
import os
import socket
import tempfile
from pathlib import Path
from uuid import uuid4

import httpx
import uvicorn
from papilio.api.application import create_app
from papilio_tasks.apps.lifecycle import Producers
from papilio_tasks.apps.schedulers.redis import create_app as tasks_app
from redis.asyncio import Redis

from src.config.providers import infrastructure_providers, task_providers
from src.config.settings import PapilioSettings
from tests.managed_ip_agent import (
    exercise_native_managed_ip,
    exercise_native_managed_ip_drains,
)
from tests.real_core_runtime import RealCoreRuntime
from tests.test_core_provisioning_agent_workflow import (
    CoreProvisioningAgentFixture,
)


class ManagedIpAgentWorkflowTest(CoreProvisioningAgentFixture):
    async def enable_owned_lease_fixture(self):
        self.raw["core_runtime"].update(enabled=True, allow_start=True)
        self.raw["core_provisioning"] = {
            "mode": "installed_only",
            "batch_size": 8,
            "scan_cron": "* * * * *",
            "max_memberships": 16,
            "observation_seconds": 15,
            "max_attempts": 3,
            "retry_seconds": 1,
        }
        self.raw["core_usage"]["mode"] = "disabled"
        self.raw["operations"].update(
            automation_default_mode="interval",
            automation_min_interval_seconds=1,
            automation_default_interval_seconds=1,
        )
        self.ip_namespace = "papilio:test:managed-ip:" + uuid4().hex
        self.raw["tasks"]["scheduler"].update(
            queue_name=self.ip_namespace + ":jobs",
            schedule_prefix=self.ip_namespace + ":schedules",
            result_prefix=self.ip_namespace + ":results",
        )
        self.settings = PapilioSettings.model_validate(self.raw)
        await self.client.aclose()
        await self.app.state.dishka_container.close()
        native = tasks_app(
            self.settings.tasks.scheduler,
            providers=task_providers(self.settings),
            modules=self.settings.app.modules,
        )
        self.ip_producers = Producers(native)
        await self.ip_producers.connect()
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
        logged = await self.client.post(
            "/v1/admin/auth/login",
            headers={"Origin": self.settings.public.admin_origin},
            json={"username": self.username, "password": self.password},
        )
        self.assertEqual(logged.status_code, 200)
        self.headers = {
            "Origin": self.settings.public.admin_origin,
            "X-CSRF-Token": logged.json()["csrf_token"],
        }

    async def asyncTearDown(self):
        producers = getattr(self, "ip_producers", None)
        if producers is not None:
            await producers.stop()
            redis = Redis.from_url(self.raw["redis"]["url"])
            try:
                # This namespace belongs only to this finite acceptance run.
                keys = await redis.keys(self.ip_namespace + ":*")
                if keys:
                    await redis.delete(*keys)
            finally:
                await redis.aclose()
        await super().asyncTearDown()

    async def tls_bundle(self, runtime, inputs):
        # These are ephemeral fixture materials, copied privately before any
        # native export so the managed child uses exactly the same file paths.
        inputs.mkdir(mode=0o700)
        certificate, key = inputs / "cert.pem", inputs / "key.pem"
        certificate.write_bytes(runtime.certificate.read_bytes())
        key.write_bytes(runtime.key.read_bytes())
        certificate.chmod(0o600)
        key.chmod(0o600)
        ports = [runtime.port(), runtime.port(), runtime.port()]
        nodes = await asyncio.gather(
            *(
                self.post(
                    "/v1/admin/network/nodes",
                    {
                        "code": "managed_ip_" + letter + "_" + self.suffix,
                        "label": "Owned IP node " + letter,
                        "public_host": "127.0.0.1",
                        "public_port": port,
                        "protocol": "vless_tls",
                    },
                )
                for letter, port in zip("ab", ports[::2], strict=True)
            )
        )
        enabled = await asyncio.gather(
            *(
                self.client.patch(
                    f"/v1/admin/network/nodes/{row['node']['id']}/enabled",
                    headers=self.headers,
                    json={"enabled": True},
                )
                for row in nodes
            )
        )
        self.assertTrue(all(row.status_code == 200 for row in enabled))
        cores = await asyncio.gather(
            *(
                self.post(
                    f"/v1/admin/network/nodes/{row['node']['id']}/cores",
                    {"code": "ip", "label": "Owned IP core", "kind": "xray"},
                )
                for row in nodes
            )
        )
        owners = [
            (nodes[0], cores[0]),
            (nodes[0], cores[0]),
            (nodes[1], cores[1]),
        ]
        configurations = await asyncio.gather(
            *(
                self.post(
                    "/v1/admin/network/configurations",
                    {
                        "node_id": node["node"]["id"],
                        "core_id": core["id"],
                        "listen_port": port,
                        "label": "Owned IP inbound " + str(index),
                        "options": {
                            "protocol": "vless_tls",
                            "listen_address": "127.0.0.1",
                            "server_name": "localhost",
                            "certificate_path": str(certificate),
                            "private_key_path": str(key),
                            "transport": "tcp",
                        },
                    },
                )
                for index, ((node, core), port) in enumerate(
                    zip(owners, ports, strict=True)
                )
            )
        )
        # Explicit native editor, rather than privately rewriting the bundle.
        edited = await asyncio.gather(
            *(
                self.client.put(
                    f"/v1/admin/network/configurations/{row['id']}/server-json",
                    headers=self.headers,
                    json={
                        "expected_revision": row["revision"],
                        "reason": "Owned private lease fixture log policy",
                        "document": {
                            "mode": "managed",
                            "source": (
                                '{"inbounds":[{"$papilio":"managed"}],'
                                '"log":{"loglevel":"none"}}'
                            ),
                        },
                    },
                )
                for row in configurations
            )
        )
        self.assertTrue(all(row.status_code == 200 for row in edited))
        configurations = [row.json()["data"] for row in edited]
        hosts = await asyncio.gather(
            *(
                self.post(
                    f"/v1/admin/network/configurations/{row['id']}/hosts",
                    {
                        "label": "Owned IP host",
                        "address": "127.0.0.1",
                        "port": port,
                        "is_enabled": True,
                    },
                )
                for row, port in zip(configurations, ports, strict=True)
            )
        )
        group = await self.post(
            "/v1/admin/network/host-groups",
            {
                "code": "ip_" + self.suffix,
                "title": "Owned IP bundle",
                "is_enabled": True,
            },
        )
        linked = await asyncio.gather(
            *(
                self.client.put(
                    f"/v1/admin/network/host-groups/{group['id']}/hosts/{host['id']}",
                    headers=self.headers,
                    json={"is_enabled": True, "sort_order": index},
                )
                for index, host in enumerate(hosts)
            )
        )
        self.assertTrue(all(row.status_code == 200 for row in linked))
        plan = await self.post(
            "/v1/admin/plans",
            {
                "code": "ip_" + self.suffix,
                "title": "Owned three-profile IP plan",
                "quota_bytes": 1000000000,
                "duration_days": 30,
                "price_rial": 100000,
                "group_id": group["id"],
                "fulfillment": {
                    **self.raw["fulfillment"]["policy"],
                    "automatic": True,
                    "activation": "all",
                    "expiry_start": "activation",
                    "renewal_trigger": "expiry",
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
                "display_name": "Owned IP buyer",
                "telegram_id": int(self.suffix, 16),
            },
        )
        topup = await self.post(
            "/v1/admin/payments/topups",
            {"customer_id": customer["id"], "amount_rial": 300000},
        )
        await self.post(
            f"/v1/admin/payments/topups/{topup['id']}/approve",
            {"bank_reference": "ip_" + self.suffix},
        )
        purchase = {
            "customer_id": customer["id"],
            "plan_id": plan["id"],
            "purchase_key": "ip_" + self.suffix,
            "auto_renew": False,
        }
        subscription = await self.post("/v1/admin/subscriptions", purchase)
        rows = await self.get(
            f"/v1/admin/provisioning?subscription_id={subscription['id']}"
        )
        self.assertEqual(rows["meta"]["pager"]["total_items"], 1)
        foreign = await self.post(
            "/v1/admin/network/nodes",
            {
                "code": "ip_foreign_" + self.suffix,
                "label": "Owned unassigned admission node",
                "public_host": "127.0.0.1",
                "public_port": runtime.port(),
                "protocol": "vless_tls",
            },
        )
        return {
            "nodes": nodes,
            "cores": cores,
            "configurations": configurations,
            "subscription": subscription,
            "request": rows["data"][0],
            "customer": customer,
            "purchase": purchase,
            "foreign_node": foreign,
        }

    async def exercise_owned_ip_workflow(self, operation):
        runtime_binary = os.environ.get("PAPILIO_RUNTIME_TEST_BINARY")
        managed_binary = os.environ.get("PAPILIO_MANAGED_TEST_BINARY")
        binaries = os.environ.get("PAPILIO_CORE_BIN_DIR")
        if not runtime_binary or not managed_binary or not binaries:
            self.skipTest(
                "Explicit private managed/stock agent binaries required"
            )
        await self.enable_owned_lease_fixture()
        with tempfile.TemporaryDirectory(
            prefix="papilio-native-managed-ip-"
        ) as name:
            directory = Path(name)
            directory.chmod(0o700)
            self.assertLessEqual(os.getloadavg()[0], 8)
            runtime = await asyncio.to_thread(
                RealCoreRuntime(directory, Path(binaries), 15).__enter__
            )
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            server = uvicorn.Server(
                uvicorn.Config(
                    self.app,
                    lifespan="off",
                    access_log=False,
                    log_level="error",
                )
            )
            serving = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                sale = await self.tls_bundle(runtime, directory / "inputs")
                cookie = self.client.cookies.get("papilio_admin")
                assert cookie is not None
                result = await asyncio.to_thread(
                    operation,
                    directory,
                    Path(runtime_binary),
                    Path(managed_binary),
                    Path(binaries),
                    f"http://127.0.0.1:{listener.getsockname()[1]}",
                    {**self.headers, "Cookie": "papilio_admin=" + cookie},
                    sale,
                    runtime,
                    self.raw,
                    self.ip_namespace,
                )
                self.assertTrue(all(result.values()))
            finally:
                server.should_exit = True
                await serving
                listener.close()
                await asyncio.to_thread(runtime.__exit__, None, None, None)

    async def test_native_two_node_source_ip_presence_leases(self):
        await self.exercise_owned_ip_workflow(exercise_native_managed_ip)

    async def test_native_two_node_source_ip_policy_drains(self):
        await self.exercise_owned_ip_workflow(
            exercise_native_managed_ip_drains
        )
