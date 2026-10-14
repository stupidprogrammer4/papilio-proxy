"""Isolated real-core admission/session evidence; never final accounting."""

import base64
import json
import socket
import struct
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from socketserver import BaseRequestHandler, ThreadingTCPServer
from typing import cast

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from tests.core_usage_agent import _exact, _wait
from tests.real_core_runtime import RealCoreRuntime


@dataclass(frozen=True)
class DrainProbePolicy:
    operation_seconds: int
    connect_seconds: float
    exchange_seconds: float
    startup_seconds: float
    cleanup_seconds: float
    max_response_bytes: int
    max_payload_bytes: int
    connection_capacity: int

    def validate(self):
        assert all(value > 0 for value in vars(self).values())
        assert self.connection_capacity >= 3
        assert self.max_payload_bytes >= 32


class EchoHandler(BaseRequestHandler):
    def handle(self):
        server = cast("OwnedEcho", self.server)
        self.request.settimeout(server.policy.exchange_seconds)
        try:
            while True:
                payload = self.request.recv(
                    server.policy.max_payload_bytes + 1
                )
                if not payload:
                    return
                if len(payload) > server.policy.max_payload_bytes:
                    return
                self.request.sendall(payload)
        except OSError:
            pass


class OwnedEcho(ThreadingTCPServer):
    daemon_threads = False

    def __init__(self, policy):
        self.policy = policy
        self.owned = {}
        self.owned_lock = threading.Lock()
        self.closing = False
        super().__init__(("127.0.0.1", 0), EchoHandler)

    def get_request(self):
        request, address = super().get_request()
        with self.owned_lock:
            if (
                self.closing
                or len(self.owned) >= self.policy.connection_capacity
            ):
                request.close()
                raise OSError("Owned echo capacity exceeded")
            self.owned[id(request)] = request
        return request, address

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self.owned_lock:
                self.owned.pop(id(request), None)

    def server_close(self):
        with self.owned_lock:
            self.closing = True
            for request in self.owned.values():
                try:
                    request.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                request.close()
        super().server_close()
        assert not self.owned, "Owned echo connections survived cleanup"


def _stream(socks_port, echo_port, policy):
    connection = socket.create_connection(
        ("127.0.0.1", socks_port), timeout=policy.connect_seconds
    )
    try:
        connection.sendall(b"\x05\x01\x00")
        assert _exact(connection, 2) == b"\x05\x00", (
            "Owned SOCKS negotiation failed"
        )
        connection.sendall(
            b"\x05\x01\x00\x01"
            + socket.inet_aton("127.0.0.1")
            + struct.pack("!H", echo_port)
        )
        reply = _exact(connection, 4)
        if reply[1] != 0:
            raise OSError("Owned stream admission denied")
        sizes = {1: 4, 4: 16}
        size = _exact(connection, 1)[0] if reply[3] == 3 else sizes[reply[3]]
        _exact(connection, size + 2)
        connection.settimeout(policy.exchange_seconds)
        return connection
    except BaseException:
        connection.close()
        raise


def _exchange(connection, marker):
    connection.sendall(marker)
    assert _exact(connection, len(marker)) == marker, (
        "Owned persistent stream did not echo exact marker"
    )


def _counters(binary, port, identity, policy):
    result = subprocess.run(
        [
            str(binary),
            "api",
            "statsquery",
            f"-server=127.0.0.1:{port}",
            f"-timeout={policy.operation_seconds}",
            f"-pattern=user>>>{identity}>>>traffic>>>",
        ],
        capture_output=True,
        timeout=policy.operation_seconds + policy.cleanup_seconds,
    )
    assert result.returncode == 0, "Owned management Stats RPC failed"
    assert len(result.stdout) + len(result.stderr) <= policy.max_response_bytes
    counters = {}
    for item in json.loads(result.stdout).get("stat", []):
        name = item["name"]
        assert name in {
            f"user>>>{identity}>>>traffic>>>uplink",
            f"user>>>{identity}>>>traffic>>>downlink",
        }, "Unbound counter returned"
        assert name not in counters, "Duplicate counter returned"
        counters[name] = int(item.get("value", 0))
    assert len(counters) == 2 and all(v >= 0 for v in counters.values())
    return {
        direction: counters[f"user>>>{identity}>>>traffic>>>{direction}"]
        for direction in ("uplink", "downlink")
    }


def exercise_remove_inbound(root: Path, policy: DrainProbePolicy):
    """Measure existing sessions separately from new inbound admission."""
    policy.validate()
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="papilio-drain-probe-") as name:
        directory = Path(name)
        directory.chmod(0o700)
        with ExitStack() as resources:
            runtime = resources.enter_context(
                RealCoreRuntime(
                    directory,
                    root / "data/core-validation/bin",
                    policy.operation_seconds,
                    tls_connection_capacity=policy.connection_capacity,
                )
            )
            version = subprocess.run(
                [str(runtime.binaries / "xray"), "version"],
                capture_output=True,
                timeout=policy.operation_seconds,
                check=True,
            )
            assert b"26.3.27" in version.stdout, "Untested Xray pin"
            echo = OwnedEcho(policy)
            resources.callback(echo.server_close)
            worker = threading.Thread(target=echo.serve_forever)
            worker.start()
            resources.callback(worker.join, policy.cleanup_seconds)
            resources.callback(echo.shutdown)
            echo_port = echo.server_address[1]
            api_port = runtime.port()
            private = X25519PrivateKey.generate()

            def encode(value):
                return base64.urlsafe_b64encode(value).decode().rstrip("=")

            secret = encode(
                private.private_bytes(
                    serialization.Encoding.Raw,
                    serialization.PrivateFormat.Raw,
                    serialization.NoEncryption(),
                )
            )
            public = encode(
                private.public_key().public_bytes(
                    serialization.Encoding.Raw, serialization.PublicFormat.Raw
                )
            )
            inbounds, streams = [], {}
            for label in ("a", "b"):
                identity, email = str(uuid.uuid4()), "drain-" + label
                port, socks_port = runtime.port(), runtime.port()
                inbounds.append(
                    {
                        "tag": "node-probe-" + label,
                        "listen": "127.0.0.1",
                        "port": port,
                        "protocol": "vless",
                        "settings": {
                            "clients": [
                                {
                                    "id": identity,
                                    "email": email,
                                    "level": 0,
                                    "flow": "xtls-rprx-vision",
                                }
                            ],
                            "decryption": "none",
                        },
                        "streamSettings": {
                            "network": "tcp",
                            "security": "reality",
                            "realitySettings": {
                                "dest": f"localhost:{runtime.handshake_port}",
                                "serverNames": ["localhost"],
                                "privateKey": secret,
                                "shortIds": ["0123456789abcdef"],
                            },
                        },
                    }
                )
                outbound = {
                    "tag": "proxy",
                    "type": "vless",
                    "server": "127.0.0.1",
                    "server_port": port,
                    "uuid": identity,
                    "flow": "xtls-rprx-vision",
                    "tls": {
                        "enabled": True,
                        "server_name": "localhost",
                        "utls": {"enabled": True, "fingerprint": "chrome"},
                        "reality": {
                            "enabled": True,
                            "public_key": public,
                            "short_id": "0123456789abcdef",
                        },
                    },
                }
                path = runtime.file(
                    label + "-client.json",
                    json.dumps(
                        {
                            "inbounds": [
                                {
                                    "type": "socks",
                                    "listen": "127.0.0.1",
                                    "listen_port": socks_port,
                                }
                            ],
                            "outbounds": [outbound],
                            "route": {"final": "proxy"},
                        }
                    ),
                )
                streams[label] = {
                    "email": email,
                    "port": port,
                    "socks_port": socks_port,
                    "path": path,
                }
            inbounds.append(
                {
                    "tag": "papilio-stats-api",
                    "listen": "127.0.0.1",
                    "port": api_port,
                    "protocol": "dokodemo-door",
                    "settings": {"address": "127.0.0.1"},
                }
            )
            path = runtime.file(
                "probe-server.json",
                json.dumps(
                    {
                        "stats": {},
                        "api": {
                            "tag": "papilio-stats-api",
                            "services": ["StatsService", "HandlerService"],
                        },
                        "policy": {
                            "levels": {
                                "0": {
                                    "statsUserUplink": True,
                                    "statsUserDownlink": True,
                                }
                            }
                        },
                        "inbounds": inbounds,
                        "outbounds": [
                            {"tag": "direct", "protocol": "freedom"},
                            {"tag": "deny", "protocol": "blackhole"},
                        ],
                        "routing": {
                            "rules": [
                                {
                                    "type": "field",
                                    "inboundTag": ["papilio-stats-api"],
                                    "outboundTag": "papilio-stats-api",
                                },
                                {
                                    "type": "field",
                                    "inboundTag": [
                                        "node-probe-a",
                                        "node-probe-b",
                                    ],
                                    "port": str(api_port),
                                    "outboundTag": "deny",
                                },
                            ]
                        },
                    }
                ),
            )
            runtime.start(
                "probe-server",
                [str(runtime.binaries / "xray"), "run", "-config", str(path)],
            )

            def listener_ready(port):
                try:
                    with socket.create_connection(
                        ("127.0.0.1", port), timeout=policy.connect_seconds
                    ):
                        return True
                except OSError:
                    return False

            for label, stream in streams.items():
                runtime.start(
                    label + "-client",
                    [
                        str(runtime.binaries / "sing-box"),
                        "run",
                        "-c",
                        str(stream["path"]),
                    ],
                )
                _wait(
                    lambda: listener_ready(stream["socks_port"]),
                    bool,
                    "Owned subscriber listener unavailable",
                    seconds=policy.startup_seconds,
                )
                connection = _stream(stream["socks_port"], echo_port, policy)
                resources.callback(connection.close)
                stream["connection"] = connection
                _exchange(connection, (label + "-before").encode() * 4)
            before = _counters(
                runtime.binaries / "xray", api_port, "drain-a", policy
            )
            removed = subprocess.run(
                [
                    str(runtime.binaries / "xray"),
                    "api",
                    "rmi",
                    f"-server=127.0.0.1:{api_port}",
                    f"-timeout={policy.operation_seconds}",
                    "node-probe-a",
                ],
                capture_output=True,
                timeout=policy.operation_seconds + policy.cleanup_seconds,
            )
            assert removed.returncode == 0, "Owned RemoveInbound RPC failed"
            assert (
                len(removed.stdout) + len(removed.stderr)
                <= policy.max_response_bytes
            )
            with socket.socket() as direct:
                direct.settimeout(policy.connect_seconds)
                assert (
                    direct.connect_ex(("127.0.0.1", streams["a"]["port"])) != 0
                ), "Removed inbound still admits TCP connections"
            try:
                fresh = _stream(streams["a"]["socks_port"], echo_port, policy)
            except OSError:
                pass
            else:
                fresh.close()
                raise AssertionError("Removed inbound admitted fresh VLESS")
            # A successful marker proves this existing session survived.
            existing_survives = False
            try:
                _exchange(streams["a"]["connection"], b"a-after-removal" * 2)
                existing_survives = True
            except OSError:
                pass
            _exchange(streams["b"]["connection"], b"b-after-removal" * 2)
            after = _counters(
                runtime.binaries / "xray", api_port, "drain-a", policy
            )
            _counters(runtime.binaries / "xray", api_port, "drain-b", policy)
            if existing_survives:
                assert all(after[key] > before[key] for key in before), (
                    "Surviving stream did not advance its exact counters"
                )
            result = {
                "xray_version": "26.3.27",
                "remove_inbound_rpc": "succeeded",
                "new_a_admission": "denied",
                "existing_a_session": "survived"
                if existing_survives
                else "closed",
                "unaffected_b_session": "verified",
                "management_rpc": "verified",
                "counter_before": before,
                "counter_after": after,
                "final_accounting_claimed": False,
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
        assert not worker.is_alive(), "Owned echo worker survived cleanup"
        return result
