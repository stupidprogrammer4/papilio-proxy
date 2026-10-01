"""Temporary end-to-end Xray test; refuses a node with customer credentials."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from smoke_api import _api

ROOT = Path("/opt/papilio-proxy/data/xray")
IMAGE = "ghcr.io/xtls/xray-core@sha256:592ec4d11f656db95598d01e76dbcc6e002d67360b96a5436500a938230f52c7"
CLIENT = "papilio-xray-smoke-client"
SOCKS_PORT = 10809


def _run(*args: str, timeout: int = 25) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(args, capture_output=True, check=False, timeout=timeout)


def _client_config(protocol: str, identifier: str, node: dict[str, object]) -> dict[str, object]:
    server = node["server"]
    assert isinstance(server, dict)
    reality = server["Reality"]
    vmess = server["VMess"]
    assert isinstance(reality, dict) and isinstance(vmess, dict)
    if protocol == "vless":
        outbound = {
            "protocol": "vless",
            "settings": {"vnext": [{"address": "127.0.0.1", "port": reality.get("Port", 8443),
                                    "users": [{"id": identifier, "encryption": "none",
                                               "flow": "xtls-rprx-vision"}]}]},
            "streamSettings": {"network": "tcp", "security": "reality",
                               "realitySettings": {"serverName": "bot.amupouya.org",
                                                   "fingerprint": "chrome",
                                                   "publicKey": node["publicKey"],
                                                   "shortId": reality["ShortIDs"][0]}},
        }
    else:
        outbound = {
            "protocol": "vmess",
            "settings": {"vnext": [{"address": "127.0.0.1", "port": vmess.get("Port", 8444),
                                    "users": [{"id": identifier, "alterId": 0,
                                               "security": "auto"}]}]},
            "streamSettings": {"network": "ws", "security": "tls",
                               "wsSettings": {"path": vmess["WebSocketPath"],
                                              "host": "bot.amupouya.org"},
                               "tlsSettings": {"serverName": "bot.amupouya.org",
                                               "allowInsecure": False,
                                               "alpn": ["http/1.1"]}},
        }
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{"listen": "127.0.0.1", "port": SOCKS_PORT,
                      "protocol": "socks", "settings": {"auth": "noauth", "udp": False}}],
        "outbounds": [outbound],
    }


def _probe(protocol: str, identifier: str, node: dict[str, object]) -> bool:
    with tempfile.TemporaryDirectory(prefix="papilio-xray-smoke-") as directory:
        os.chown(directory, 65532, 65532)
        path = Path(directory) / "client.json"
        path.write_text(json.dumps(_client_config(protocol, identifier, node)))
        os.chown(path, 65532, 65532)
        path.chmod(0o400)
        start = _run(
            "docker", "run", "-d", "--rm", "--name", CLIENT,
            "--network", "host", "--user", "65532:65532", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "-v", f"{path}:/client.json:ro", "--entrypoint", "/usr/local/bin/xray",
            IMAGE, "run", "-config", "/client.json",
        )
        if start.returncode:
            raise RuntimeError("Disposable Xray client failed to start")
        try:
            for _ in range(30):
                try:
                    with socket.create_connection(("127.0.0.1", SOCKS_PORT), timeout=1):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Disposable SOCKS client did not listen")
            response = _run(
                "curl", "-fsS", "--socks5-hostname", f"127.0.0.1:{SOCKS_PORT}",
                "--max-time", "12", "-o", "/dev/null", "-w", "%{http_code}",
                "https://bot.amupouya.org/admin", timeout=15,
            )
            return response.returncode == 0 and response.stdout == b"200"
        finally:
            _run("docker", "rm", "-f", CLIENT)


def main() -> int:
    config = json.loads((ROOT / "config.json").read_text())
    inbounds = config["inbounds"][:2]
    if any(inbound["settings"]["clients"] for inbound in inbounds):
        print("Refusing smoke test: node has live users", file=sys.stderr)
        return 1
    node = json.loads((ROOT / "node.json").read_text())
    identifier = str(uuid4())
    email = "smoke-" + uuid4().hex
    inbounds[0]["settings"]["clients"] = [
        {"id": identifier, "email": email, "flow": "xtls-rprx-vision", "level": 0}
    ]
    inbounds[1]["settings"]["clients"] = [
        {"id": identifier, "email": email, "alterId": 0, "level": 0}
    ]
    try:
        added = _api("adu", "/dev/stdin", payload=json.dumps({"inbounds": inbounds}).encode())
        if added.returncode:
            print("Could not add disposable users", file=sys.stderr)
            return 1
        for protocol in ("vless", "vmess"):
            if not _probe(protocol, identifier, node):
                print(f"{protocol} data-plane request failed", file=sys.stderr)
                return 1
            print(f"{protocol}: verified HTTPS request through proxy")
        counters = _api("statsquery", f"-pattern={email}")
        if counters.returncode:
            print("Per-user traffic counters were not readable", file=sys.stderr)
            return 1
        stats = json.loads(counters.stdout)
        values = [
            item.get("value", 0) for item in stats.get("stat", [])
            if email in item.get("name", "") and "traffic" in item.get("name", "")
        ]
        if not values or sum(values) <= 0:
            print("Per-user traffic counters did not advance", file=sys.stderr)
            return 1
        print(f"Shared user traffic counters: {sum(values)} bytes")
        for tag in ("vless-reality-in", "vmess-ws-tls-in"):
            removed = _api("rmu", f"-tag={tag}", email)
            if removed.returncode:
                print(f"Failed to revoke disposable {tag} user", file=sys.stderr)
                return 1
        if _probe("vless", identifier, node) or _probe("vmess", identifier, node):
            print("Revoked user retained access", file=sys.stderr)
            return 1
        print("Both protocols reject new traffic after revocation")
        return 0
    finally:
        # No disposable identity is written to the persistent server config.
        _run("docker", "rm", "-f", CLIENT)
        restarted = _run("docker", "restart", "papilio-xray-1", timeout=30)
        if restarted.returncode:
            print("CRITICAL: Xray cleanup restart failed", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
