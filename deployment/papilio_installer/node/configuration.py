"""Validate private bootstrap inputs and render explicit native runtime seeds."""

import hashlib
import ipaddress
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

BOOTSTRAP_FILES = frozenset({"agent.json", "server.crt", "server.key", "client-ca.crt"})
ENVIRONMENTS = ("dev", "test", "sandbox", "production")


@dataclass(frozen=True)
class NodeInstallSettings:
    environment: str = "production"
    inbound_tag: str = "vless"
    listen_address: str = "0.0.0.0"
    port: int = 8443
    restart_seconds: int = 3

    def validate(self) -> None:
        if self.environment not in ENVIRONMENTS:
            raise ValueError("Choose dev, test, sandbox or production.")
        if (
            not isinstance(self.inbound_tag, str)
            or not self.inbound_tag.strip()
            or self.inbound_tag != self.inbound_tag.strip()
            or len(self.inbound_tag) > 80
            or self.inbound_tag == "management"
            or any(ord(char) < 32 for char in self.inbound_tag)
        ):
            raise ValueError(
                "Choose a nonempty inbound tag without outer whitespace or management."
            )
        ipaddress.ip_address(self.listen_address)
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("The inbound port must be between 1 and 65535.")
        if type(self.restart_seconds) is not int or not 1 <= self.restart_seconds <= 2147483647:
            raise ValueError("Choose a positive restart delay in seconds.")


@dataclass(frozen=True)
class Bootstrap:
    node_id: UUID
    deployment_id: UUID
    runtime: dict[str, Any] = field(repr=False)
    files: dict[str, bytes] = field(repr=False)
    sha256: str


def core_api_address(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("The bootstrap requires a loopback Xray API address.")
    host, separator, port = value.rpartition(":")
    if not separator or not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise ValueError("The Xray API port is invalid.")
    if not ipaddress.ip_address(host.removeprefix("[").removesuffix("]")).is_loopback:
        raise ValueError("The Xray API must remain on a literal loopback address.")
    return value


def inspect_bootstrap(path: Path, *, byte_limit: int = 1048576) -> Bootstrap:
    if type(byte_limit) is not int or byte_limit < 1:
        raise ValueError("The bootstrap byte limit must be positive.")
    if path.stat().st_size > byte_limit:
        raise ValueError("The bootstrap archive exceeds the configured byte limit.")
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if (
            len(members) != len(BOOTSTRAP_FILES)
            or {row.filename for row in members} != BOOTSTRAP_FILES
            or sum(row.file_size for row in members) > byte_limit
            or any(row.is_dir() or row.flag_bits & 1 for row in members)
        ):
            raise ValueError("Choose the unmodified four-file panel bootstrap archive.")
        files = {row.filename: archive.read(row) for row in members}
    runtime = json.loads(files["agent.json"])
    if not isinstance(runtime, dict):
        raise ValueError("The bootstrap configuration must be a JSON object.")
    for name, expected in (
        ("tls_certificate_file", "server.crt"),
        ("tls_key_file", "server.key"),
        ("client_ca_file", "client-ca.crt"),
    ):
        if runtime.get(name) != expected:
            raise ValueError("Bootstrap credential paths must use the issued private files.")
    core_api_address(runtime.get("xray_api_address"))
    shutdown = runtime.get("shutdown_timeout_seconds")
    if type(shutdown) is not int or not 1 <= shutdown <= 2147483647:
        raise ValueError("The bootstrap shutdown timeout is invalid.")
    return Bootstrap(
        UUID(runtime["node_id"]),
        UUID(runtime["deployment_id"]),
        runtime,
        files,
        hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def seed_xray(bootstrap: Bootstrap, settings: NodeInstallSettings) -> dict[str, Any]:
    settings.validate()
    return {
        "log": {"loglevel": "warning"},
        "api": {
            "tag": "management",
            "listen": core_api_address(bootstrap.runtime.get("xray_api_address")),
            "services": ["HandlerService", "StatsService"],
        },
        "stats": {},
        "inbounds": [
            {
                "tag": settings.inbound_tag,
                "listen": settings.listen_address,
                "port": settings.port,
                "protocol": "vless",
                "settings": {"clients": [], "decryption": "none"},
            }
        ],
        "outbounds": [{"protocol": "freedom", "tag": "direct"}],
    }


def unit_path(path: Path) -> str:
    value = str(path)
    if not path.is_absolute() or re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError("A service path must be an absolute path without control characters.")
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")


def service_unit(root: Path, bootstrap: Bootstrap, settings: NodeInstallSettings) -> str:
    settings.validate()
    folder = unit_path(root)
    credentials = "\n".join(
        f'LoadCredential="{name}:{folder}/credentials/{name}"'
        for name in sorted(BOOTSTRAP_FILES | {"xray.json"})
    )
    stop_seconds = 3 * bootstrap.runtime["shutdown_timeout_seconds"] + 5
    return f'''[Unit]
Description=Papilio node {bootstrap.node_id} ({settings.environment})
Wants=network-online.target
After=network-online.target

[Service]
Type=exec
DynamicUser=yes
{credentials}
ExecStart="{folder}/bin/papilio-agent" -config %d/agent.json
Restart=on-failure
RestartSec={settings.restart_seconds}s
TimeoutStopSec={stop_seconds}s
KillMode=mixed
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
UMask=0077

[Install]
WantedBy=multi-user.target
'''
