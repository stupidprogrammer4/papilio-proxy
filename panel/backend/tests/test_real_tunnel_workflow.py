import asyncio
import os
import tempfile
from pathlib import Path
from unittest import skipUnless

from cryptography import x509
from cryptography.x509.oid import NameOID

from tests.real_kernel_runtime import KernelCoreRuntime
from tests.test_foundations_workflow import FoundationsWorkflowTest
from tests.test_openvpn_workflow import OpenVpnWorkflowTest
from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowTest,
)


@skipUnless(
    os.environ.get("PAPILIO_CORE_DOCKER_IMAGE"),
    "isolated real tunnels require explicit opt-in",
)
class RealTunnelWorkflowTest(
    StaffAdministrationWorkflowTest, FoundationsWorkflowTest
):
    async def tunnel(self, protocol, transport, topology="tun"):
        root = (
            Path(
                os.environ.get(
                    "PAPILIO_CORE_RESULTS_DIR",
                    tempfile.mkdtemp(prefix="papilio-tunnel-"),
                )
            )
            / f"{protocol}-{transport}-{topology}"
        )
        runtime = await asyncio.to_thread(
            KernelCoreRuntime(
                root, os.environ["PAPILIO_CORE_DOCKER_IMAGE"], 20
            ).__enter__
        )
        try:
            _, subscription = await self.paid_subscription()
            node = (
                await self.post(
                    "/v1/admin/network/nodes",
                    {
                        "code": "tunnel_" + self.suffix,
                        "label": "Owned isolated tunnel",
                        "public_host": runtime.server_ip,
                        "public_port": 45322,
                        "protocol": protocol,
                    },
                )
            )["node"]
            if protocol == "wireguard":
                options = {
                    "protocol": protocol,
                    "server_address": "10.44.0.1/24",
                    "client_subnet": "10.44.0.0/24",
                    "allowed_ips": ["10.44.0.1/32"],
                    "dns": ["1.1.1.1"],
                }
            else:
                options = OpenVpnWorkflowTest.options(transport=transport)
                if topology == "tap":
                    options["topology"] = {
                        "mode": "tap",
                        "network": "10.43.0.0/24",
                        "bridge_address": "10.43.0.1",
                        "pool_start": "10.43.0.10",
                        "pool_end": "10.43.0.20",
                    }
                options.update(
                    management_socket="/tmp/papilio-test.sock",
                    redirect_gateway=False,
                    routes=[],
                    dns=[],
                )
            inbound = await self.post(
                "/v1/admin/network/configurations",
                {
                    "node_id": node["id"],
                    "label": "Owned tunnel acceptance",
                    "options": options,
                },
            )
            profile = await self.post(
                f"/v1/admin/network/configurations/{inbound['id']}/profiles",
                {
                    "subscription_id": subscription["id"],
                    **(
                        {"client_address": "10.44.0.2/32"}
                        if protocol == "wireguard"
                        else {}
                    ),
                },
            )
            server = await self.post(
                f"/v1/admin/network/configurations/{inbound['id']}/server-download"
            )
            client = await self.post(
                f"/v1/admin/network/configurations/profiles/{profile['id']}/client-download"
            )
            identity = None
            if protocol == "openvpn":
                certificate = x509.load_pem_x509_certificate(
                    OpenVpnWorkflowTest.inline(
                        client["content"], "cert"
                    ).encode()
                )
                identity = certificate.subject.get_attributes_for_oid(
                    NameOID.COMMON_NAME
                )[0].value
            await asyncio.to_thread(
                runtime.traffic,
                server["content"],
                client["content"],
                protocol,
                identity,
            )
        finally:
            await asyncio.to_thread(runtime.__exit__, None, None, None)

    async def test_native_wireguard_real_tunnel_traffic(self):
        await self.tunnel("wireguard", "udp")

    async def test_native_openvpn_udp_real_tunnel_traffic(self):
        await self.tunnel("openvpn", "udp")

    async def test_native_openvpn_tcp_real_tunnel_traffic(self):
        await self.tunnel("openvpn", "tcp")

    async def test_native_openvpn_udp_bridge_real_tunnel_traffic(self):
        await self.tunnel("openvpn", "udp", "tap")

    async def test_native_openvpn_tcp_bridge_real_tunnel_traffic(self):
        await self.tunnel("openvpn", "tcp", "tap")
