"""Reversible, zero-customer Xray HandlerService smoke test on the VPS."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

CONFIG = Path("/opt/papilio-proxy/data/xray/config.json")
CONTAINER = "papilio-xray-1"
API = "127.0.0.1:10085"


def _api(*arguments: str, payload: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "/usr/local/bin/xray", "api",
         arguments[0], f"--server={API}", *arguments[1:]],
        input=payload, capture_output=True, check=False, timeout=20,
    )


def main() -> int:
    config = json.loads(CONFIG.read_text())
    inbounds = config["inbounds"][:2]
    if any(inbound["settings"]["clients"] for inbound in inbounds):
        print("Refusing smoke test: node has live users", file=sys.stderr)
        return 1
    identifier = str(uuid4())
    email = "smoke-" + uuid4().hex
    inbounds[0]["settings"]["clients"] = [
        {"id": identifier, "email": email, "flow": "xtls-rprx-vision", "level": 0}
    ]
    inbounds[1]["settings"]["clients"] = [
        {"id": identifier, "email": email, "alterId": 0, "level": 0}
    ]
    try:
        result = _api("adu", "/dev/stdin", payload=json.dumps({"inbounds": inbounds}).encode())
        if result.returncode:
            print("Xray add-user API failed:", result.stderr.decode(errors="replace").strip()[-300:], file=sys.stderr)
            return 1
        for tag in ("vless-reality-in", "vmess-ws-tls-in"):
            count = _api("inboundusercount", f"-tag={tag}")
            if count.returncode:
                print(f"Xray user-count API failed for {tag}", file=sys.stderr)
                return 1
            print(f"{tag}: {count.stdout.decode().strip()}")
        print(result.stdout.decode().strip())
        return 0
    finally:
        # The test identity is never persisted in config.json. Restart revokes
        # it even if an API call partially succeeded.
        subprocess.run(["docker", "restart", CONTAINER], check=True, capture_output=True, timeout=30)


if __name__ == "__main__":
    raise SystemExit(main())
