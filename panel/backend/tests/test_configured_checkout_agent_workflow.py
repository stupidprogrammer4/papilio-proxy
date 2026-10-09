"""Durable owned checkout installs every paid configured-bundle membership."""

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
from sqlalchemy import text

from src.config.providers import infrastructure_providers, task_providers
from src.config.settings import PapilioSettings
from tests.configured_checkout_agent import exercise_configured_checkout
from tests.real_core_runtime import RealCoreRuntime
from tests.test_core_provisioning_agent_workflow import (
    CoreProvisioningAgentFixture,
)


class ConfiguredCheckoutAgentWorkflowTest(CoreProvisioningAgentFixture):
    async def enable_configured_checkout(self):
        self.raw["purchase_intents"] = {
            "policy": {
                "enabled": True,
                "admission_mode": "require_ready_bundle",
                "default_expiry_seconds": 3600,
            },
            "scan_cron": "* * * * *",
            "recheck_seconds": 1,
        }
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
        self.checkout_namespace = "papilio:test:configured:" + uuid4().hex
        self.raw["tasks"]["scheduler"].update(
            queue_name=self.checkout_namespace + ":jobs",
            schedule_prefix=self.checkout_namespace + ":schedules",
            result_prefix=self.checkout_namespace + ":results",
        )
        self.settings = PapilioSettings.model_validate(self.raw)
        await self.client.aclose()
        await self.app.state.dishka_container.close()
        native = tasks_app(
            self.settings.tasks.scheduler,
            providers=task_providers(self.settings),
            modules=self.settings.app.modules,
        )
        self.checkout_producers = Producers(native)
        await self.checkout_producers.connect()
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
        response = await self.client.post(
            "/v1/admin/auth/login",
            headers={"Origin": self.settings.public.admin_origin},
            json={"username": self.username, "password": self.password},
        )
        self.assertEqual(response.status_code, 200)
        self.headers = {
            "Origin": self.settings.public.admin_origin,
            "X-CSRF-Token": response.json()["csrf_token"],
        }

    async def asyncTearDown(self):
        producers = getattr(self, "checkout_producers", None)
        if producers is not None:
            await producers.stop()
            redis = Redis.from_url(self.raw["redis"]["url"])
            try:
                keys = [
                    key
                    async for key in redis.scan_iter(
                        match=self.checkout_namespace + ":*"
                    )
                ]
                if keys:
                    await redis.delete(*keys)
            finally:
                await redis.aclose()
        await super().asyncTearDown()

    async def configured_bundle(self, runtime):
        ports = [runtime.port(), runtime.port()]
        node = await self.post(
            "/v1/admin/network/nodes",
            {
                "code": "checkout_" + self.suffix,
                "label": "Owned configured checkout node",
                "public_host": "127.0.0.1",
                "public_port": ports[0],
                "protocol": "vless_reality",
            },
        )
        enabled = await self.client.patch(
            f"/v1/admin/network/nodes/{node['node']['id']}/enabled",
            headers=self.headers,
            json={"enabled": True},
        )
        self.assertEqual(enabled.status_code, 200)
        core = await self.post(
            f"/v1/admin/network/nodes/{node['node']['id']}/cores",
            {"code": "checkout", "label": "Owned bundle core", "kind": "xray"},
        )
        group = await self.post(
            "/v1/admin/network/host-groups",
            {
                "code": "checkout_" + self.suffix,
                "title": "Owned two-host bundle",
                "is_enabled": True,
            },
        )
        configurations = await asyncio.gather(
            *(
                self.post(
                    "/v1/admin/network/configurations",
                    {
                        "node_id": node["node"]["id"],
                        "core_id": core["id"],
                        "listen_port": port,
                        "label": f"Owned bundle inbound {index}",
                        "options": {
                            "protocol": "vless_reality",
                            "listen_address": "127.0.0.1",
                            "server_name": "localhost",
                            "target_port": runtime.handshake_port,
                        },
                    },
                )
                for index, port in enumerate(ports)
            )
        )
        hosts = await asyncio.gather(
            *(
                self.post(
                    f"/v1/admin/network/configurations/{configuration['id']}/hosts",
                    {
                        "label": f"Owned bundle host {index}",
                        "address": "127.0.0.1",
                        "port": port,
                        "is_enabled": True,
                    },
                )
                for index, (configuration, port) in enumerate(
                    zip(configurations, ports, strict=True)
                )
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
        self.assertTrue(all(row.status_code == 200 for row in memberships))
        plan = await self.post(
            "/v1/admin/plans",
            {
                "code": "checkout_" + self.suffix,
                "title": "Owned configured bundle",
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
        return node, core, plan, [row["id"] for row in configurations]

    async def test_native_wallet_configured_bundle_checkout_installation(self):
        binary = os.getenv("PAPILIO_RUNTIME_TEST_BINARY")
        binaries = os.getenv("PAPILIO_CORE_BIN_DIR")
        if not binary or not binaries:
            self.skipTest("Explicit owned real-core/runtime opt-in required")
        await self.enable_configured_checkout()
        with tempfile.TemporaryDirectory(
            prefix="papilio-checkout-native-"
        ) as name:
            directory = Path(name)
            directory.chmod(0o700)
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
                (
                    node,
                    core,
                    plan,
                    configurations,
                ) = await self.configured_bundle(runtime)
                identity = {
                    "telegram_id": 3300000000 + int(self.suffix[:6], 16),
                    "display_name": "Owned configured checkout buyer",
                }
                bot_headers = {
                    "X-Papilio-Bot-Key": self.settings.security.bot_service_key
                }
                home = await self.client.post(
                    "/v1/bot/home", headers=bot_headers, json=identity
                )
                self.assertEqual(home.status_code, 200)
                customer_id = home.json()["data"]["customer_id"]
                topup = await self.post(
                    "/v1/admin/payments/topups",
                    {"customer_id": customer_id, "amount_rial": 300000},
                )
                await self.post(
                    f"/v1/admin/payments/topups/{topup['id']}/approve",
                    {"bank_reference": "checkout_" + self.suffix},
                )
                offered = await self.client.post(
                    f"/v1/bot/checkouts/offers/{plan['id']}",
                    headers=bot_headers,
                    json=identity,
                )
                self.assertEqual(offered.status_code, 200)
                offer = offered.json()["data"]
                self.assertEqual(offer["delivery_mode"], "configured_bundle")
                self.assertEqual(offer["membership_count"], 2)
                body = {
                    "request_key": "configured_" + self.suffix,
                    "plan_id": plan["id"],
                    "funding_mode": "wallet_only",
                    "expected_offer_sha256": offer["offer_sha256"],
                    "expected_price_rial": offer["price_rial"],
                    "auto_renew": True,
                    "expiry_seconds": offer["default_expiry_seconds"],
                    "changed_offer_action": "require_confirmation",
                    "customer_id": customer_id + 987654321,
                }
                created = await self.client.post(
                    "/v1/bot/checkouts",
                    headers=bot_headers,
                    json={**identity, **body},
                )
                self.assertEqual(created.status_code, 200)
                intent = created.json()["data"]
                self.assertEqual(intent["customer_id"], customer_id)
                self.assertEqual(intent["state"], "ready")
                self.assertIsNone(intent["subscription_id"])
                wallet = await self.get(
                    f"/v1/admin/payments/wallets/{customer_id}"
                )
                self.assertEqual(wallet["data"]["balance_rial"], 300000)
                cookie = self.client.cookies.get("papilio_admin")
                assert cookie is not None
                base_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
                config = {
                    "enabled": True,
                    "api_url": base_url,
                    "node_code": node["node"]["code"],
                    "state_directory": str(directory / "checkout-journal"),
                    "binaries": {
                        "xray": str(Path(binaries) / "xray"),
                        "sing_box": str(Path(binaries) / "sing-box"),
                    },
                    "poll_interval_ms": 50,
                    "http_timeout_ms": 5000,
                    "max_response_bytes": 2097152,
                    "max_idle_connections": 4,
                    "page_size": 16,
                    "max_pages_per_poll": 4,
                    "max_artifacts": 16,
                    "max_artifact_bytes": 1048576,
                    "max_bundle_bytes": 2097152,
                    "max_journal_bytes": 1048576,
                    "max_receipts": 32,
                    "max_cores": 4,
                    "validation_timeout_ms": 5000,
                    "startup_grace_ms": 150,
                    "stop_timeout_ms": 2000,
                    "max_processes": 4,
                    "provisioning": {
                        "mode": "installed_only",
                        "max_memberships": 16,
                        "max_receipts": 32,
                        "page_size": 16,
                        "max_pages_per_core": 4,
                        "max_tasks_per_poll": 32,
                    },
                }
                result = await asyncio.to_thread(
                    exercise_configured_checkout,
                    directory,
                    Path(binary),
                    base_url,
                    {**self.headers, "Cookie": "papilio_admin=" + cookie},
                    node,
                    core,
                    runtime,
                    self.raw,
                    self.checkout_namespace,
                    intent["id"],
                    identity,
                    body,
                    configurations,
                    200000,
                    config,
                )
                self.assertEqual(result[3:], (2, 1, 200000))
                async with self.connection.uow() as fresh:
                    count = await fresh.execute(
                        text(
                            "SELECT COUNT(*) FROM tbl_wallet_entries e "
                            "JOIN tbl_wallets w ON w.id=e.wallet_id "
                            "WHERE w.customer_id=:customer "
                            "AND e.reason='purchase'"
                        ),
                        {"customer": customer_id},
                    )
                    self.assertEqual(count.scalar_one(), 1)
            finally:
                server.should_exit = True
                await serving
                listener.close()
                await asyncio.to_thread(runtime.__exit__, None, None, None)
