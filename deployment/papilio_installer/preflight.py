"""Read-only host compatibility and port checks."""

import platform
import socket
import subprocess
from pathlib import Path

from .configuration import InstallSettings

MATRIX = {"ubuntu": {"22.04", "24.04", "26.04"}, "debian": {"12", "13"}}


def check_ports(settings: InstallSettings) -> None:
    ports = (
        (settings.http_port, settings.https_port) if settings.tls_enabled else (settings.http_port,)
    )
    if settings.local_node:
        ports += (settings.node_port,)
    for port in ports:
        try:
            with socket.socket() as listener:
                listener.bind((settings.bind_address, port))
        except OSError as error:
            raise ValueError(
                f"The requested port {port} is unavailable; no service was changed."
            ) from error


def check_host(*, allow_unverified: bool = False) -> None:
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "aarch64"}:
        raise ValueError("This alpha installer targets amd64/arm64 Linux only.")
    metadata = {}
    for line in Path("/etc/os-release").read_text().splitlines():
        key, _, value = line.partition("=")
        metadata[key] = value.strip('"')
    candidate = metadata.get("VERSION_ID") in MATRIX.get(metadata.get("ID", ""), set())
    if not candidate and not allow_unverified:
        raise ValueError(
            "This OS is outside the candidate matrix. "
            "Use --allow-unverified-host for an explicit development attempt."
        )
    subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"], check=True, capture_output=True
    )
    subprocess.run(["docker", "compose", "version"], check=True, capture_output=True)
