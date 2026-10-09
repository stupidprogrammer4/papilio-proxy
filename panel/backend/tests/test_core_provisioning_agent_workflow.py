import asyncio
import os
import socket
import tempfile
from pathlib import Path

import uvicorn

from src.modules.network.core_runtime.domain.memberships import (
    CoreProvisioningCapacity,
)
from src.modules.operations.automation.domain.dtos import ScheduleMode
from tests.real_core_runtime import RealCoreRuntime
from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowFixture,
)


class CoreProvisioningAgentFixture(StaffAdministrationWorkflowFixture):
    async def runtime_sale(self, runtime, kind, quota, duration):
        port = runtime.port()
        node = await self.post(
            "/v1/admin/network/nodes",
            {
                "code": "installed_" + self.suffix,
                "label": "Owned purchase node",
                "public_host": "127.0.0.1",
                "public_port": port,
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
            {
                "code": "installed",
                "label": "Owned purchase core",
                "kind": kind,
            },
        )
        configuration = await self.post(
            "/v1/admin/network/configurations",
            {
                "node_id": node["node"]["id"],
                "core_id": core["id"],
                "listen_port": port,
                "label": "Owned purchase inbound",
                "options": {
                    "protocol": "vless_reality",
                    "listen_address": "127.0.0.1",
                    "server_name": "localhost",
                    "target_port": runtime.handshake_port,
                },
            },
        )
        host = await self.post(
            f"/v1/admin/network/configurations/{configuration['id']}/hosts",
            {
                "label": "Owned local endpoint",
                "address": "127.0.0.1",
                "port": port,
                "is_enabled": True,
            },
        )
        group = await self.post(
            "/v1/admin/network/host-groups",
            {
                "code": "installed_" + self.suffix,
                "title": "Owned group",
                "is_enabled": True,
            },
        )
        membership = await self.client.put(
            f"/v1/admin/network/host-groups/{group['id']}/hosts/{host['id']}",
            headers=self.headers,
            json={"is_enabled": True, "sort_order": 0},
        )
        self.assertEqual(membership.status_code, 200)
        plan = await self.post(
            "/v1/admin/plans",
            {
                "code": "installed_" + self.suffix,
                "title": "Owned purchase plan",
                "quota_bytes": quota,
                "duration_days": duration,
                "price_rial": 100000,
                "group_id": group["id"],
                "fulfillment": {
                    **self.raw["fulfillment"]["policy"],
                    "automatic": True,
                    "activation": "all",
                    "expiry_start": "activation",
                    "renewal_trigger": "quota"
                    if duration is None
                    else "expiry",
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
                "display_name": "Owned buyer",
                "telegram_id": int(self.suffix, 16),
            },
        )
        topup = await self.post(
            "/v1/admin/payments/topups",
            {"customer_id": customer["id"], "amount_rial": 300000},
        )
        await self.post(
            f"/v1/admin/payments/topups/{topup['id']}/approve",
            {"bank_reference": "installed_" + self.suffix},
        )
        purchase = {
            "customer_id": customer["id"],
            "plan_id": plan["id"],
            "purchase_key": "installed_" + self.suffix,
            "auto_renew": True,
        }
        subscription = await self.post("/v1/admin/subscriptions", purchase)
        requests = await self.get(
            f"/v1/admin/provisioning?subscription_id={subscription['id']}"
        )
        self.assertEqual(requests["meta"]["pager"]["total_items"], 1)
        request = next(iter(requests["data"]))
        return node, core, subscription, request, purchase

    async def installed_purchase(self, kind, quota, duration):
        from tests.core_provisioning_agent import exercise_installed_purchase

        binary = os.environ.get("PAPILIO_RUNTIME_TEST_BINARY")
        binaries = os.environ.get("PAPILIO_CORE_BIN_DIR")
        if not binary or not binaries:
            self.skipTest(
                "Explicit owned runtime binary and real-core opt-in required"
            )
        capacity = self.settings.core_runtime
        assert capacity is not None
        capacity.enabled = True
        capacity.allow_start = True
        self.raw["core_runtime"].update(enabled=True, allow_start=True)
        policy = {
            "mode": "installed_only",
            "batch_size": 8,
            "scan_cron": "* * * * *",
            "max_memberships": 16,
            "observation_seconds": 15,
            "max_attempts": 3,
            "retry_seconds": 1,
        }
        self.settings.core_provisioning = (
            CoreProvisioningCapacity.model_validate(policy)
        )
        self.raw["core_provisioning"] = policy
        self.settings.operations.automation_default_mode = (
            ScheduleMode.INTERVAL
        )
        self.settings.operations.automation_min_interval_seconds = 1
        self.settings.operations.automation_default_interval_seconds = 1
        self.raw["operations"].update(
            automation_default_mode="interval",
            automation_min_interval_seconds=1,
            automation_default_interval_seconds=1,
        )
        with tempfile.TemporaryDirectory(
            prefix="papilio-installed-native-"
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
                    subscription,
                    request,
                    purchase,
                ) = await self.runtime_sale(runtime, kind, quota, duration)
                self.assertEqual(subscription["status"], "pending_provision")
                cookie = self.client.cookies.get("papilio_admin")
                assert cookie is not None
                result = await asyncio.to_thread(
                    exercise_installed_purchase,
                    directory,
                    Path(binary),
                    Path(binaries),
                    f"http://127.0.0.1:{listener.getsockname()[1]}",
                    {**self.headers, "Cookie": "papilio_admin=" + cookie},
                    node,
                    core,
                    runtime,
                    self.raw,
                    subscription["id"],
                    request["id"],
                    int(self.suffix, 16),
                )
                self.assertEqual(
                    result, ("active", "applied", request["generation"])
                )
                replay = await self.post("/v1/admin/subscriptions", purchase)
                self.assertEqual(replay["id"], subscription["id"])
                wallet = (
                    await self.get(
                        f"/v1/admin/payments/wallets/{subscription['customer_id']}"
                    )
                )["data"]
                self.assertEqual(wallet["balance_rial"], 200000)
                fresh = (
                    await self.get(
                        f"/v1/admin/subscriptions/{subscription['id']}"
                    )
                )["data"]
                self.assertEqual(fresh["status"], "active")
                self.assertEqual(fresh["quota_bytes"], quota)
                self.assertEqual(fresh["duration_days"], duration)
                self.assertEqual(fresh["expires_at"] is None, duration is None)
            finally:
                server.should_exit = True
                await serving
                listener.close()
                await asyncio.to_thread(runtime.__exit__, None, None, None)


class CoreProvisioningAgentWorkflowTest(CoreProvisioningAgentFixture):
    async def test_native_xray_quota_and_duration_purchase_installation(self):
        await self.installed_purchase("xray", 1000000000, 30)

    async def test_native_sing_box_quota_only_purchase_installation(self):
        await self.installed_purchase("sing_box", 1000000000, None)

    async def test_native_xray_duration_only_purchase_installation(self):
        await self.installed_purchase("xray", None, 30)
