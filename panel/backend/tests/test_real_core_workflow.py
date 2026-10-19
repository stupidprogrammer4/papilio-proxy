import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest import skipUnless

from tests.real_core_runtime import RealCoreRuntime
from tests.test_foundations_workflow import FoundationsWorkflowTest
from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowTest,
)


@skipUnless(
    os.environ.get("PAPILIO_CORE_BIN_DIR"),
    "real core binaries require explicit opt-in",
)
class RealCoreWorkflowTest(
    StaffAdministrationWorkflowTest, FoundationsWorkflowTest
):
    async def configuration(
        self,
        runtime,
        kind,
        protocol,
        transport,
        index,
        subscription_id,
        server_document=None,
    ):
        port = runtime.port()
        registered = await self.post(
            "/v1/admin/network/nodes",
            {
                "code": f"core_{self.suffix}_{index}",
                "label": "Owned loopback core",
                "public_host": "127.0.0.1",
                "public_port": port,
                "protocol": protocol,
            },
        )
        node = registered["node"]
        core = await self.post(
            f"/v1/admin/network/nodes/{node['id']}/cores",
            {
                "code": f"instance_{index}",
                "label": "Owned acceptance instance",
                "kind": kind,
            },
        )
        options = {"protocol": protocol, "listen_address": "127.0.0.1"}
        if protocol == "vless_reality":
            options.update(
                server_name="localhost", target_port=runtime.handshake_port
            )
        elif protocol != "shadowsocks":
            options.update(
                server_name="localhost",
                certificate_path=str(runtime.certificate),
                private_key_path=str(runtime.key),
            )
            if protocol != "hysteria2":
                options.update(
                    transport=transport,
                    transport_path="/acceptance"
                    if transport == "ws"
                    else "acceptance"
                    if transport == "grpc"
                    else None,
                )
        inbound = await self.post(
            "/v1/admin/network/configurations",
            {
                "node_id": node["id"],
                "core_id": core["id"],
                "listen_port": port,
                "label": "Owned real-core inbound",
                "options": options,
            },
        )
        profile = await self.post(
            f"/v1/admin/network/configurations/{inbound['id']}/profiles",
            {"subscription_id": subscription_id},
        )
        if server_document is not None:
            saved = await self.client.put(
                f"/v1/admin/network/configurations/{inbound['id']}/server-json",
                headers=self.headers,
                json={
                    "expected_revision": inbound["revision"],
                    "reason": "Real Xray managed document compatibility",
                    "document": server_document,
                },
            )
            self.assertEqual(saved.status_code, 200, saved.text)
        server = await self.post(
            f"/v1/admin/network/configurations/{inbound['id']}/server-download"
        )
        client = await self.post(
            f"/v1/admin/network/configurations/profiles/{profile['id']}/client-download"
        )
        return kind, protocol, transport, server["content"], client["content"]

    @staticmethod
    def run_matrix(runtime, configurations):
        outcomes = []
        for kind, protocol, transport, server, client in configurations:
            name = f"{kind}-{protocol}-{transport}"
            try:
                runtime.traffic(
                    name,
                    "sing-box" if kind == "sing_box" else kind,
                    server,
                    client,
                )
                outcomes.append({"case": name, "passed": True})
            except Exception as error:
                outcomes.append(
                    {"case": name, "passed": False, "error": str(error)}
                )
        import json

        runtime.file("results.json", json.dumps(outcomes, indent=2))
        failures = [outcome for outcome in outcomes if not outcome["passed"]]
        assert not failures, failures

    async def test_native_exports_real_traffic_and_invalid_credentials(self):
        binary_dir = Path(os.environ["PAPILIO_CORE_BIN_DIR"]).resolve()
        root = Path(
            os.environ.get(
                "PAPILIO_CORE_RESULTS_DIR",
                tempfile.mkdtemp(prefix="papilio-real-core-"),
            )
        ).resolve()
        runtime = await asyncio.to_thread(
            RealCoreRuntime(root, binary_dir, 15).__enter__
        )
        try:
            _, subscription = await self.paid_subscription()
            cases = [
                (kind, protocol, transport)
                for kind in ("xray", "sing_box")
                for protocol in ("vless_tls", "vmess_tls", "trojan_tls")
                for transport in ("tcp", "ws", "grpc")
            ]
            cases.extend(
                (kind, protocol, "tcp")
                for kind in ("xray", "sing_box")
                for protocol in ("vless_reality", "shadowsocks")
            )
            cases.extend(
                (kind, "hysteria2", "quic")
                for kind in ("sing_box", "hysteria")
            )
            configurations = await asyncio.gather(
                *(
                    self.configuration(
                        runtime, *case, index, subscription["id"]
                    )
                    for index, case in enumerate(cases)
                )
            )
            await asyncio.to_thread(self.run_matrix, runtime, configurations)
        finally:
            await asyncio.to_thread(runtime.__exit__, None, None, None)

    async def test_managed_server_json_runs_on_real_xray(self):
        binary_dir = Path(os.environ["PAPILIO_CORE_BIN_DIR"]).resolve()
        temporary = tempfile.TemporaryDirectory(
            prefix="papilio-real-xray-json-"
        )
        root = Path(temporary.name)
        runtime = await asyncio.to_thread(
            RealCoreRuntime(root, binary_dir, 15).__enter__
        )
        try:
            _, subscription = await self.paid_subscription()
            configuration = await self.configuration(
                runtime,
                "xray",
                "vless_tls",
                "tcp",
                1,
                subscription["id"],
                {
                    "mode": "managed",
                    "source": json.dumps(
                        {
                            "inbounds": [{"$papilio": "managed"}],
                            "dns": {"servers": ["9.9.9.9"]},
                            "routing": {"domainStrategy": "IPIfNonMatch"},
                            "outbounds": [
                                {"protocol": "freedom", "tag": "custom"}
                            ],
                        }
                    ),
                },
            )
            self.assertIn('"tag": "custom"', configuration[3])
            await asyncio.to_thread(self.run_matrix, runtime, [configuration])
        finally:
            await asyncio.to_thread(runtime.__exit__, None, None, None)
            temporary.cleanup()
