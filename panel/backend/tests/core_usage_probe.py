"""Owned offline VLESS/Reality RPC diagnosis, never a native install ACK."""

import base64
import json
import shutil
import socket
import tempfile
import time
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from tests.core_usage_agent import _stats, _subscriber_rpc, _wait
from tests.real_core_runtime import RealCoreRuntime


def exercise_offline_vless(root):
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="papilio-vless-probe-") as name:
        directory = Path(name)
        directory.chmod(0o700)
        with RealCoreRuntime(
            directory, root / "data/core-validation/bin", 15
        ) as runtime:
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
            identity, short = str(uuid.uuid4()), "0123456789abcdef"
            stats, subscriber = runtime.port(), runtime.port()
            document = {
                "log": {"loglevel": "info"},
                "stats": {},
                "api": {
                    "tag": "papilio-stats-api",
                    "services": ["StatsService"],
                },
                "policy": {
                    "levels": {
                        "0": {
                            "statsUserUplink": True,
                            "statsUserDownlink": True,
                        }
                    }
                },
                "inbounds": [
                    {
                        "tag": "node-1",
                        "listen": "127.0.0.1",
                        "port": subscriber,
                        "protocol": "vless",
                        "settings": {
                            "clients": [
                                {
                                    "id": identity,
                                    "email": "opaque",
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
                                "shortIds": [short],
                            },
                        },
                    },
                    {
                        "tag": "papilio-stats-api",
                        "listen": "127.0.0.1",
                        "port": stats,
                        "protocol": "dokodemo-door",
                        "settings": {"address": "127.0.0.1"},
                    },
                ],
                "outbounds": [
                    {
                        "tag": "direct",
                        "protocol": "freedom",
                        "settings": {"redirect": f"127.0.0.1:{stats}"},
                    },
                    {"tag": "papilio-stats-deny", "protocol": "blackhole"},
                ],
                "routing": {
                    "domainStrategy": "IPOnDemand",
                    "rules": [
                        {
                            "type": "field",
                            "inboundTag": ["papilio-stats-api"],
                            "outboundTag": "papilio-stats-api",
                        },
                        {
                            "type": "field",
                            "inboundTag": ["node-1"],
                            "port": str(stats),
                            "outboundTag": "papilio-stats-deny",
                        },
                    ],
                },
            }
            outbound = {
                "type": "vless",
                "server": "127.0.0.1",
                "server_port": subscriber,
                "uuid": identity,
                "flow": "xtls-rprx-vision",
                "tls": {
                    "enabled": True,
                    "server_name": "localhost",
                    "utls": {"enabled": True, "fingerprint": "chrome"},
                    "reality": {
                        "enabled": True,
                        "public_key": public,
                        "short_id": short,
                    },
                },
            }
            redirect = document["outbounds"][0]["settings"]
            document["outbounds"][0]["settings"] = {}
            path = runtime.file("unsafe-server.json", json.dumps(document))
            process = runtime.start(
                "unsafe-server",
                [str(runtime.binaries / "xray"), "run", "-config", str(path)],
            )
            try:
                runtime.exercise(
                    "normal-vless-control", outbound, accepted=True
                )
                print({"normal_vless_http": "passed"})
                runtime.stop(process)
                document["outbounds"][0]["settings"] = redirect
                path = runtime.file("unsafe-server.json", json.dumps(document))
                process = runtime.start(
                    "unsafe-server-redirect",
                    [
                        str(runtime.binaries / "xray"),
                        "run",
                        "-config",
                        str(path),
                    ],
                )
                _wait(
                    lambda: (
                        _stats(
                            runtime.binaries / "xray", stats, "opaque"
                        ).returncode
                    ),
                    lambda code: code == 0,
                    "Owned management unavailable",
                    seconds=5,
                )
                # A direct relay separates transport from SOCKS negotiation.
                direct_port = runtime.port()
                direct = runtime.file(
                    "direct-client.json",
                    json.dumps(
                        {
                            "inbounds": [
                                {
                                    "type": "direct",
                                    "listen": "127.0.0.1",
                                    "listen_port": direct_port,
                                    "override_address": "198.51.100.10",
                                    "override_port": 80,
                                }
                            ],
                            "outbounds": [{**outbound, "tag": "proxy"}],
                            "route": {"final": "proxy"},
                        }
                    ),
                )
                client = runtime.start(
                    "direct-client",
                    [
                        str(runtime.binaries / "sing-box"),
                        "run",
                        "-c",
                        str(direct),
                    ],
                )
                try:

                    def ready():
                        try:
                            with socket.create_connection(
                                ("127.0.0.1", direct_port), timeout=0.2
                            ):
                                return True
                        except OSError:
                            return False

                    _wait(
                        ready,
                        bool,
                        "Owned direct client unavailable",
                        seconds=3,
                    )
                    result = _stats(
                        runtime.binaries / "xray",
                        direct_port,
                        "opaque",
                        timeout_seconds=4,
                    )
                    print({"direct_vless_rpc_exit": result.returncode})
                    assert result.returncode == 0, (
                        "Actual direct VLESS RPC failed"
                    )
                finally:
                    runtime.stop(client)
                _subscriber_rpc(
                    runtime,
                    outbound,
                    "198.51.100.10",
                    80,
                    "opaque",
                    "socks-vless-rpc",
                    accepted=True,
                )
                return {
                    "actual_vless_rpc": "passed",
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                }
            except BaseException:
                saved = (
                    root
                    / "data"
                    / ("core-usage-fixture-diagnostic-" + uuid.uuid4().hex)
                )
                saved.mkdir(mode=0o700)
                for file in directory.glob("*.json"):
                    shutil.copyfile(file, saved / file.name)
                    (saved / file.name).chmod(0o600)
                for file in directory.glob("*.log"):
                    shutil.copyfile(file, saved / file.name)
                    (saved / file.name).chmod(0o600)
                text = (
                    (directory / "unsafe-server.log")
                    .read_text(errors="replace")
                    .lower()
                )
                print(
                    {
                        "safe_server_phases": {
                            term: term in text
                            for term in (
                                "received request",
                                "invalid request",
                                "rejected since",
                                "failed to dial",
                                "eof",
                                "reality",
                                "handshake",
                            )
                        }
                    }
                )
                print({"private_test_diagnostic": saved.name})
                raise
            finally:
                runtime.stop(process)


def exercise_stalled_tls_concurrency(root):
    """Actual TLS handshake concurrent with a stalled accepted peer."""
    import ssl

    from tests.real_core_runtime import TrafficTarget

    started = time.monotonic()
    with tempfile.TemporaryDirectory(
        prefix="papilio-tls-concurrency-"
    ) as name:
        directory = Path(name)
        directory.chmod(0o700)
        with RealCoreRuntime(
            directory, root / "data/core-validation/bin", 1
        ) as runtime:
            stalled = socket.create_connection(
                ("127.0.0.1", runtime.handshake_port), timeout=1
            )
            try:
                context = ssl.create_default_context(
                    cafile=str(runtime.certificate)
                )
                context.minimum_version = ssl.TLSVersion.TLSv1_3
                with socket.create_connection(
                    ("127.0.0.1", runtime.handshake_port), timeout=0.5
                ) as plain:
                    plain.settimeout(0.5)
                    with context.wrap_socket(
                        plain, server_hostname="localhost"
                    ) as secured:
                        secured.sendall(
                            b"GET /proof HTTP/1.1\r\n"
                            b"Host: localhost\r\nConnection: close\r\n\r\n"
                        )
                        response = b""
                        while True:
                            data = secured.recv(4096)
                            if not data:
                                break
                            response += data
                            assert len(response) <= 8192, (
                                "Owned TLS response exceeded fixture budget"
                            )
                assert TrafficTarget.payload in response, (
                    "Concurrent owned TLS proof unavailable"
                )
                stalled.settimeout(2)
                assert stalled.recv(1) == b"", (
                    "Stalled TLS handshake exceeded owning timeout"
                )
            finally:
                stalled.close()
    return {
        "stalled_tls_concurrency": "passed",
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
