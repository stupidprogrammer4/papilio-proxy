"""Exercise the isolated Go node socket, data plane, counters and revocation."""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from smoke_data import _probe

SOCKET = os.getenv(
    "PAPILIO_SMOKE_SOCKET", "/opt/papilio-proxy/data/node-smoke/test.sock"
)


def request(method: str, path: str, data: dict[str, object] | None = None) -> object:
    command = ["curl", "-fsS", "--unix-socket", SOCKET, "-X", method]
    if data is not None:
        command.extend(["-H", "Content-Type: application/json", "--data-binary", "@-"])
    command.append("http://localhost" + path)
    result = subprocess.run(
        command, input=json.dumps(data).encode() if data is not None else None,
        capture_output=True, check=True, timeout=10,
    )
    return json.loads(result.stdout) if result.stdout else None


def main() -> None:
    identifier = str(uuid4())
    email = "smoke-" + uuid4().hex
    issued = request("POST", "/v1/ensure", {
        "id": identifier, "email": email, "label": "Papilio smoke",
        "quota_bytes": 20_000_000, "duration_days": 1,
        "baseline_uplink_bytes": 0, "baseline_downlink_bytes": 0,
    })
    assert isinstance(issued, dict)
    snapshot = issued["snapshot"]
    assert isinstance(snapshot, dict)
    assert snapshot["email"] == email
    assert snapshot["uplink_bytes"] == snapshot["downlink_bytes"] == 0
    started = datetime.fromisoformat(str(snapshot["measured_at"]))
    expires = datetime.fromisoformat(str(issued["expires_at"]))
    assert expires == started + timedelta(days=1)
    assert identifier in str(issued["vless_link"])
    print("Go node issued one zero-usage entitlement on both protocols")

    retry = request("POST", "/v1/ensure", {
        "id": identifier, "email": email, "label": "Papilio smoke",
        "quota_bytes": 20_000_000, "duration_days": 1,
        "baseline_uplink_bytes": 0, "baseline_downlink_bytes": 0,
    })
    assert isinstance(retry, dict) and retry["expires_at"] == issued["expires_at"]
    print("Provisioning retry kept the original expiry")

    node = json.loads(Path("/opt/papilio-proxy/data/xray/node.json").read_text())
    node["server"]["Reality"]["Port"] = int(os.getenv("PAPILIO_SMOKE_REALITY_PORT", "18443"))
    node["server"]["VMess"]["Port"] = int(os.getenv("PAPILIO_SMOKE_VMESS_PORT", "18444"))
    for protocol in ("vless", "vmess"):
        assert _probe(protocol, identifier, node), f"{protocol} could not pass HTTPS"
        print(f"{protocol}: verified HTTPS through Go-managed user")

    time.sleep(2)
    usage = request("GET", "/v1/usage")
    assert isinstance(usage, list) and len(usage) == 1
    assert usage[0]["uplink_bytes"] + usage[0]["downlink_bytes"] > 0
    print("Shared counters advanced")

    request("POST", "/v1/remove", {"email": email})
    assert not _probe("vless", identifier, node)
    assert not _probe("vmess", identifier, node)
    print("Both links reject new traffic after revocation")


if __name__ == "__main__":
    main()
