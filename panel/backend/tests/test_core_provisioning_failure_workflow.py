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
from tests.core_provisioning_failure import exercise_failed_purchase
from tests.real_core_runtime import RealCoreRuntime
from tests.test_core_provisioning_agent_workflow import (
    CoreProvisioningAgentFixture,
)


class CoreProvisioningFailureWorkflowTest(CoreProvisioningAgentFixture):
    async def test_native_xray_failed_purchase_revocation_refund_once(self):
        binary = os.environ.get("PAPILIO_RUNTIME_TEST_BINARY")
        binaries = os.environ.get("PAPILIO_CORE_BIN_DIR")
        if not binary or not binaries:
            self.skipTest(
                "Explicit owned runtime and real-core opt-in required"
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
            prefix="papilio-failed-native-"
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
                node, core, subscription, request, _ = await self.runtime_sale(
                    runtime, "xray", 1000000000, 30
                )
                cookie = self.client.cookies.get("papilio_admin")
                assert cookie is not None
                result = await asyncio.to_thread(
                    exercise_failed_purchase,
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
                self.assertEqual(result, ("refunded", "revoked", 300000, 1))
                fresh = (
                    await self.get(
                        f"/v1/admin/subscriptions/{subscription['id']}"
                    )
                )["data"]
                self.assertEqual(fresh["status"], "failed")
                self.assertIsNone(fresh["activated_at"])
            finally:
                server.should_exit = True
                await serving
                listener.close()
                await asyncio.to_thread(runtime.__exit__, None, None, None)
