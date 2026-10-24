"""Native node preparation, systemd installation and scoped lifecycle commands."""

import argparse
import os
import shutil
import socket
import subprocess
from contextlib import ExitStack
from pathlib import Path
from uuid import UUID

from .artifacts import download_bundle, inspect_bundle, native_platform
from .configuration import Bootstrap, NodeInstallSettings, inspect_bootstrap
from .installation import NodeInstallation, load_installation, prepare_installation


def register(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--node-home", type=Path)
    commands = parser.add_subparsers(dest="node_command", required=True)
    setup = commands.add_parser("install")
    setup.add_argument("--bootstrap", type=Path, required=True)
    setup.add_argument("--bundle", type=Path)
    setup.add_argument("--inbound-tag", default="vless")
    setup.add_argument("--listen", default="0.0.0.0")
    setup.add_argument("--port", type=int, default=8443)
    setup.add_argument("--restart-seconds", type=int, default=3)
    setup.add_argument("--bootstrap-byte-limit", type=int, default=1048576)
    setup.add_argument("--bundle-byte-limit", type=int, default=536870912)
    setup.add_argument("--prepare-only", action="store_true")
    for name in ("start", "stop", "restart", "status", "run"):
        command = commands.add_parser(name)
        command.add_argument("--node", type=UUID, required=True)
    logs = commands.add_parser("logs")
    logs.add_argument("--node", type=UUID, required=True)
    logs.add_argument("--tail", type=int, default=100)
    logs.add_argument("--follow", action="store_true")


def check_ports(bootstrap: Bootstrap, settings: NodeInstallSettings) -> None:
    addresses = (
        bootstrap.runtime["listen_address"],
        bootstrap.runtime["xray_api_address"],
        f"{settings.listen_address}:{settings.port}",
    )
    with ExitStack() as sockets:
        for address in addresses:
            host, _, port = address.rpartition(":")
            host = host.removeprefix("[").removesuffix("]")
            family = socket.AF_INET6 if ":" in host else socket.AF_INET
            listener = sockets.enter_context(socket.socket(family, socket.SOCK_STREAM))
            try:
                listener.bind((host, int(port)))
            except OSError as error:
                raise ValueError(f"Node listener is unavailable: {address}") from error


def install_service(installation: NodeInstallation) -> None:
    unit = installation.root / installation.service_name
    target = Path("/etc/systemd/system") / installation.service_name
    if (target.exists() or target.is_symlink()) and (
        target.is_symlink() or target.read_bytes() != unit.read_bytes()
    ):
        raise ValueError("The existing systemd unit differs; preserve or review it first.")
    subprocess.run(["systemd-analyze", "verify", str(unit)], check=True)
    if not target.exists():
        with target.open("xb") as output:
            os.fchmod(output.fileno(), 0o644)
            output.write(unit.read_bytes())
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", installation.service_name], check=True)


def install(arguments: argparse.Namespace, source: Path, home: Path) -> None:
    if not arguments.prepare_only and (
        os.geteuid() != 0
        or not Path("/run/systemd/system").is_dir()
        or shutil.which("systemd-analyze") is None
    ):
        raise ValueError("Native service installation requires root and a running systemd host.")
    settings = NodeInstallSettings(
        arguments.environment,
        arguments.inbound_tag,
        arguments.listen,
        arguments.port,
        arguments.restart_seconds,
    )
    settings.validate()
    bootstrap = inspect_bootstrap(arguments.bootstrap, byte_limit=arguments.bootstrap_byte_limit)
    root = home.resolve() / settings.environment / str(bootstrap.node_id)
    if not root.exists():
        check_ports(bootstrap, settings)
    selected = arguments.bundle or download_bundle(
        source, home / "cache", arguments.bundle_byte_limit
    )
    bundle = inspect_bundle(selected, native_platform(), byte_limit=arguments.bundle_byte_limit)
    installation = prepare_installation(root, bundle, bootstrap, settings)
    print(f"Native node files prepared: {installation.root}")
    if not arguments.prepare_only:
        install_service(installation)
        print("Service start requested. Check actual connectivity from the panel.")


def execute(arguments: argparse.Namespace, source: Path) -> None:
    home = arguments.node_home or arguments.home / "nodes"
    if arguments.node_command == "install":
        install(arguments, source, home)
        return
    installation = load_installation(home.resolve() / arguments.environment / str(arguments.node))
    if arguments.node_command == "run":
        binary = installation.root / "bin/papilio-agent"
        os.execv(
            binary, [str(binary), "-config", str(installation.root / "credentials/agent.json")]
        )
    if arguments.node_command == "logs":
        if arguments.tail < 1:
            raise ValueError("Choose a positive log tail count.")
        command = [
            "journalctl",
            "--unit",
            installation.service_name,
            "--lines",
            str(arguments.tail),
        ]
        command.append("--follow" if arguments.follow else "--no-pager")
    else:
        command = ["systemctl", "--no-pager", arguments.node_command, installation.service_name]
    subprocess.run(command, check=True)
