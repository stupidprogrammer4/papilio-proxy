# Local core acceptance

Verified on 2026-10-07 using configuration files and client links downloaded
from the native Papilio API, real MySQL/Redis fixtures and real core binaries.
Tests create and remove their own database schemas. Ordinary customers,
wallets, configuration credentials and services are not test inputs.

## Tested combinations

| Server runtime | Protocol and transport | Observed result |
| --- | --- | --- |
| Xray 26.3.27 | VLESS, VMess and Trojan with TLS, each over TCP, WebSocket and gRPC | All nine carried the exact HTTP payload; wrong credentials rejected |
| sing-box 1.12.25 | VLESS, VMess and Trojan with TLS, each over TCP, WebSocket and gRPC | All nine carried the exact HTTP payload; wrong credentials rejected |
| Xray 26.3.27 and sing-box 1.12.25 | VLESS/REALITY and Shadowsocks 2022 AES-256-GCM | All four carried the exact HTTP payload; wrong credentials rejected |
| Hysteria 2.6.4 and sing-box 1.12.25 | Hysteria2 over QUIC | Both carried the exact HTTP payload; wrong credentials rejected |
| OpenVPN 2.6.19 | UDP/TUN, TCP/TUN, UDP/TAP and TCP/TAP | All four carried the exact HTTP payload through actual tunnels |
| Linux WireGuard with wireguard-tools 1.0.20210914 | UDP with individual keys and preshared key | Exact HTTP payload passed through an actual kernel tunnel |

The proxy protocol clients are sing-box 1.12.25. TLS checks use a private
test certificate for localhost; verification is enabled. REALITY uses a
local TLS 1.3 handshake target. OpenVPN and WireGuard use two independent
Docker network namespaces on a temporary internal network, without published
ports. TAP tests create their required bridge inside that namespace.

The matrix contains 24 proxy connections and their 24 negative authentication
cases. Five additional native workflow tests verify OpenVPN and WireGuard
tunnels. The first matrix attempt used an invalidly formatted Shadowsocks
negative-test key; the corrected tests use a valid 32-byte wrong user key.
The final 24-case matrix passed in 104.18 seconds. TUN/WireGuard tests passed
in 45.91 seconds and TAP tests in 31.24 seconds.

## Repeat the tests

Run on Linux amd64 with the project virtual environment and an isolated
MySQL/Redis test environment. The existing native fixtures require
`PAPILIO_TEST_DATABASE_URL` and `PAPILIO_TEST_REDIS_URL`; the database account
must be able to create/drop the test-owned schemas. Never point integration
tests at production infrastructure.

Fetch the pinned upstream artifacts into a new private destination, from the
project root:

```bash
.venv/bin/python panel/backend/scripts/fetch_test_cores.py \
  --manifest proxy/core-test-releases.json \
  --destination data/core-validation/bin \
  --timeout 30
```

The downloader checks the archive digest before extracting its single named
binary. It does not start a core or overwrite an existing binary. Release
URLs and SHA-256 digests are recorded in
[core-test-releases.json](core-test-releases.json).

Run the native API export and authentication matrix from `panel/backend`:

```bash
export PAPILIO_CORE_BIN_DIR="$(realpath ../../data/core-validation/bin)"
export PAPILIO_CORE_RESULTS_DIR="$(realpath -m ../../data/core-validation/results)"
../../.venv/bin/pytest -q \
  tests/test_real_core_workflow.py::RealCoreWorkflowTest::test_native_exports_real_traffic_and_invalid_credentials
```

For tunnel testing, set `PAPILIO_CORE_DOCKER_IMAGE` to the ID of a trusted,
locally available Linux base image with a root user. The tests mount local
`/usr`, `/usr/lib` and `/usr/lib64` read-only and use the installed OpenVPN,
WireGuard, IP and Python tools. Docker access, `/dev/net/tun` and container
`NET_ADMIN` capability are required. No privileged container or host network
is used.

```bash
../../.venv/bin/pytest -q \
  tests/test_real_tunnel_workflow.py::RealTunnelWorkflowTest::test_native_wireguard_real_tunnel_traffic \
  tests/test_real_tunnel_workflow.py::RealTunnelWorkflowTest::test_native_openvpn_udp_real_tunnel_traffic \
  tests/test_real_tunnel_workflow.py::RealTunnelWorkflowTest::test_native_openvpn_tcp_real_tunnel_traffic \
  tests/test_real_tunnel_workflow.py::RealTunnelWorkflowTest::test_native_openvpn_udp_bridge_real_tunnel_traffic \
  tests/test_real_tunnel_workflow.py::RealTunnelWorkflowTest::test_native_openvpn_tcp_bridge_real_tunnel_traffic
```

Each case cleans up its core processes and network namespaces, including on
failure. Generated configuration files, keys and logs remain under the
private results directory for diagnosis; do not publish them. The test
environment variables explicitly opt into these temporary executions.

## Boundaries

- This proves the listed generated exports accept credentials and carry local
  traffic with the listed versions. It does not validate arbitrary edited
  server JSON, additional versions, every cipher or every certificate option.
- OpenVPN management admission is a controlled certificate-identity test
  endpoint. Production node installation, the Go management adapter and
  actual quota/expiry/IP-policy enforcement are separate acceptance gates.
- No real bank transaction, live Telegram message, remote deployment or
  Iranian mobile-network measurement is included. Network reachability,
  latency and reliability need tests on the selected nodes and access networks.
- Temporary core processes, tunnel interfaces, containers and Docker networks
  were stopped/removed after the run. Local panel services remain available.
