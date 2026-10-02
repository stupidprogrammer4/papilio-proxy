"""Install the pinned official Hysteria core on the existing node, without opening sales."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
from pathlib import Path

ROOT = Path("/opt/papilio-proxy/data/hysteria")
URL = "https://github.com/HyNetworks/hysteria/releases/download/app/v2.12.3/hysteria-linux-amd64"
SHA256 = "8c7a68a906998b747a0db87586e364f995fbfddb95693ae6e2fdb68a6e920d3e"


def private_file(path: Path, payload: str, mode: int = 0o400) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, "w") as file:
        file.write(payload)
        file.flush()
        os.fsync(file.fileno())
    os.chown(path, 65532, 10001)


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit("Run as root on the existing VPS")
    ROOT.mkdir(mode=0o750, exist_ok=True)
    os.chown(ROOT, 0, 10001)
    os.chmod(ROOT, 0o750)
    binary = ROOT / "hysteria"
    if not binary.exists():
        subprocess.run(["curl", "-fsSL", "--max-time", "60", URL, "-o", str(binary)], check=True)
    if hashlib.sha256(binary.read_bytes()).hexdigest() != SHA256:
        raise SystemExit("Hysteria binary checksum mismatch")
    binary.chmod(0o555)
    if (ROOT / "node.json").exists() or (ROOT / "server.json").exists():
        if not all((ROOT / name).is_file() for name in ("node.json", "server.json")):
            raise SystemExit("Incomplete Hysteria setup; refusing credential rotation")
        print("Pinned Hysteria configuration already present")
        return
    node = json.loads(Path("/opt/papilio-proxy/data/xray/node.json").read_text())
    host = node["server"]["VMess"]["ServerName"]
    obfs, api_secret = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    config = {
        "host": host, "port": 18447, "server_name": host, "obfs_password": obfs,
        "api_url": "http://127.0.0.1:10088", "api_secret": api_secret,
        "auth_listen": "127.0.0.1:10087", "server_config": "/etc/hysteria/server.json",
    }
    server = {
        "listen": "0.0.0.0:18447",
        "tls": {"cert": "/etc/xray/certs/fullchain.pem", "key": "/etc/xray/certs/privkey.pem"},
        "obfs": {"type": "salamander", "salamander": {"password": obfs}},
        "auth": {"type": "http", "http": {"url": "http://127.0.0.1:10087/auth"}},
        "trafficStats": {"listen": "127.0.0.1:10088", "secret": api_secret},
        "ignoreClientBandwidth": True,
        "acl": {"inline": ["reject(" + network + ")" for network in (
            "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
            "169.254.0.0/16", "100.64.0.0/10", "0.0.0.0/8", "::1/128", "fc00::/7", "fe80::/10",
        )]},
    }
    private_file(ROOT / "server.json", json.dumps(server))
    private_file(ROOT / "node.json", json.dumps(config))
    print("Official Hysteria configured with private Go auth and shared accounting")


if __name__ == "__main__":
    main()
