"""One-time VPS bootstrap for an empty Xray node; never provisions customers."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path("/opt/papilio-proxy/data/xray")
KEYPAIR = ROOT / "keypair.txt"
CONFIG = ROOT / "config.json"
NODE = ROOT / "node.json"
RENDERER = Path("/opt/papilio-proxy/data/xray/papilio-proxy")


def _write_private(path: Path, content: bytes, owner: int) -> None:
    temporary = path.with_suffix(path.suffix + ".next")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temporary, owner, owner)
        os.chmod(temporary, 0o400)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    if CONFIG.exists() or NODE.exists():
        print("Xray already bootstrapped; refusing to overwrite node state", file=sys.stderr)
        return 1
    if not KEYPAIR.is_file() or not RENDERER.is_file():
        print("Xray keypair or Go renderer is missing", file=sys.stderr)
        return 1
    fields = dict(
        line.split(": ", 1) for line in KEYPAIR.read_text().splitlines() if ": " in line
    )
    private = fields.get("PrivateKey", "")
    public = fields.get("Password (PublicKey)", "")
    if len(private) != 43 or len(public) != 43:
        print("Xray keypair is invalid", file=sys.stderr)
        return 1
    short_id = secrets.token_hex(8)
    ws_path = "/p/" + secrets.token_hex(12)
    request = {
        "server": {
            "Reality": {
                "ListenAddress": "0.0.0.0", "Port": 8443,
                "Dest": "127.0.0.1:443", "ServerNames": ["bot.amupouya.org"],
                "PrivateKey": private, "ShortIDs": [short_id],
            },
            "VMess": {
                "ListenAddress": "0.0.0.0", "Port": 8444,
                "ServerName": "bot.amupouya.org", "WebSocketPath": ws_path,
                "CertificateFile": "/etc/xray/certs/fullchain.pem",
                "KeyFile": "/etc/xray/certs/privkey.pem",
            },
            "StatsAPIListen": "127.0.0.1:10085",
        },
        "users": [],
    }
    rendered = subprocess.run(
        [str(RENDERER), "render"], input=json.dumps(request).encode(),
        capture_output=True, check=False, timeout=10,
    )
    if rendered.returncode:
        print("Go renderer rejected the node configuration", file=sys.stderr)
        return 1
    _write_private(NODE, json.dumps({"server": request["server"], "publicKey": public}).encode(), 0)
    _write_private(CONFIG, rendered.stdout, 65532)
    print("Empty Xray node configuration created; customer count: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
