"""Opt-in native first-slice usage gate; no ordinary node processes."""

import asyncio
import os
import socket
import tempfile
from pathlib import Path

import uvicorn

from src.modules.network.core_runtime.domain.memberships import (
    CoreProvisioningCapacity,
)
from src.modules.network.core_runtime.domain.usage import CoreUsageCapacity
from src.modules.operations.automation.domain.dtos import ScheduleMode
from tests.core_usage_agent import exercise_native_usage
from tests.real_core_runtime import RealCoreRuntime
from tests.resource_reports import ResourceReportPolicy, pass_resource_report
from tests.test_core_provisioning_agent_workflow import (
    CoreProvisioningAgentFixture,
)


class CoreUsageAgentWorkflowTest(CoreProvisioningAgentFixture):
    async def second_usage_sale(self, runtime, node, customer_id):
        port = runtime.port()
        core = await self.post(
            f"/v1/admin/network/nodes/{node['node']['id']}/cores",
            {
                "code": "usage_peer",
                "label": "Owned usage peer",
                "kind": "xray",
            },
        )
        configuration = await self.post(
            "/v1/admin/network/configurations",
            {
                "node_id": node["node"]["id"],
                "core_id": core["id"],
                "listen_port": port,
                "label": "Owned usage peer inbound",
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
                "label": "Owned usage peer endpoint",
                "address": "127.0.0.1",
                "port": port,
                "is_enabled": True,
            },
        )
        group = await self.post(
            "/v1/admin/network/host-groups",
            {
                "code": "usage_peer_" + self.suffix,
                "title": "Owned usage peer group",
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
                "code": "usage_peer_" + self.suffix,
                "title": "Owned larger grant",
                "quota_bytes": 1000000000,
                "duration_days": 30,
                "price_rial": 100000,
                "group_id": group["id"],
                "quota_policy": {
                    **self.raw["usage"]["policy"],
                    "grant_bytes": 2000000,
                },
                "fulfillment": {
                    **self.raw["fulfillment"]["policy"],
                    "automatic": True,
                    "activation": "all",
                    "expiry_start": "activation",
                    "renewal_trigger": "expiry",
                },
            },
        )
        enabled = await self.client.patch(
            f"/v1/admin/plans/{plan['id']}/active",
            headers=self.headers,
            json={"is_active": True},
        )
        self.assertEqual(enabled.status_code, 200)
        subscription = await self.post(
            "/v1/admin/subscriptions",
            {
                "customer_id": customer_id,
                "plan_id": plan["id"],
                "purchase_key": "usage_peer_" + self.suffix,
                "auto_renew": False,
            },
        )
        requests = await self.get(
            f"/v1/admin/provisioning?subscription_id={subscription['id']}"
        )
        self.assertEqual(requests["meta"]["pager"]["total_items"], 1)
        return core, subscription, requests["data"][0]

    async def test_native_xray_usage_accounting_and_managed_isolation(self):
        binary, binaries = (
            os.environ.get("PAPILIO_RUNTIME_TEST_BINARY"),
            os.environ.get("PAPILIO_CORE_BIN_DIR"),
        )
        if not binary or not binaries:
            self.skipTest(
                "Explicit owned Go runtime and real-core opt-in required"
            )
        assert self.settings.core_runtime is not None
        self.settings.core_runtime.enabled = True
        self.settings.core_runtime.allow_start = True
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
        self.settings.usage.policy.grant_bytes = 1000000
        self.settings.usage.policy.grant_seconds = 300
        self.raw["usage"]["policy"].update(
            grant_bytes=1000000, grant_seconds=300
        )
        with tempfile.TemporaryDirectory(prefix="papilio-real-usage-") as name:
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
                    first,
                    first_subscription,
                    first_request,
                    _,
                ) = await self.runtime_sale(runtime, "xray", 1000000000, 30)
                (
                    second,
                    second_subscription,
                    second_request,
                ) = await self.second_usage_sale(
                    runtime, node, first_subscription["customer_id"]
                )
                ports = {
                    first["id"]: runtime.port(),
                    second["id"]: runtime.port(),
                }
                usage = {
                    "mode": "observe",
                    "stats_ports": ports,
                    "max_profiles": 16,
                    "max_document_bytes": 1048576,
                    "observation_seconds": 15,
                    "max_node_endpoints": 8,
                }
                self.settings.core_usage = CoreUsageCapacity.model_validate(
                    usage
                )
                self.raw["core_usage"] = usage
                cookie = self.client.cookies.get("papilio_admin")
                assert cookie is not None
                report_directory = os.getenv("PAPILIO_ACCEPTANCE_REPORT_DIR")
                report_policy = (
                    ResourceReportPolicy(
                        Path(report_directory),
                        int(
                            os.getenv(
                                "PAPILIO_ACCEPTANCE_REPORT_MAX_BYTES", "4096"
                            )
                        ),
                    )
                    if report_directory
                    else None
                )
                result = await asyncio.to_thread(
                    exercise_native_usage,
                    directory,
                    Path(binary),
                    Path(binaries),
                    f"http://127.0.0.1:{listener.getsockname()[1]}",
                    {**self.headers, "Cookie": "papilio_admin=" + cookie},
                    node,
                    (first, second),
                    (first_subscription, second_subscription),
                    (first_request, second_request),
                    ports,
                    runtime,
                    self.raw,
                    resource_report_policy=report_policy,
                )
                self.assertEqual(result["allocated_bytes"], [1000000, 2000000])
                self.assertTrue(
                    all(value > 0 for value in result["used_bytes"])
                )
            finally:
                server.should_exit = True
                await serving
                listener.close()
                await asyncio.to_thread(runtime.__exit__, None, None, None)

            # Mark passed only after assertions AND owned fixture cleanup.
            pass_resource_report(result["resource_report"])
