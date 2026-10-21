"""User-facing native installation and lifecycle commands."""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .archives import backup, restore
from .configuration import (
    ENVIRONMENTS,
    Installation,
    InstallSettings,
    load_settings,
    replace_private,
)
from .docker import Compose
from .launcher import ManagedLauncher
from .preflight import check_host, check_ports
from .releases import download_release


def selected_settings(arguments: argparse.Namespace) -> InstallSettings:
    if arguments.settings_file is not None:
        return load_settings(arguments.settings_file)
    if arguments.environment == "production" and not arguments.host:
        raise ValueError("Production requires --host with this server's domain or IPv4 address.")
    settings = InstallSettings.from_options(
        environment=arguments.environment,
        instance=arguments.instance,
        host=arguments.host or "localhost",
        bind_address=arguments.bind,
        http_port=arguments.port,
        https_port=arguments.https_port,
        scheme=arguments.scheme,
    )
    settings.validate()
    return settings


def install(arguments: argparse.Namespace) -> None:
    source = arguments.source.resolve()
    if not (source / "VERSION").is_file() or not (source / "deployment/compose.yml").is_file():
        raise ValueError("Choose an extracted Papilio release as --source.")
    settings = selected_settings(arguments)
    root = arguments.home.resolve() / settings.environment / settings.instance
    if root.exists():
        installation = Installation.load(root)
        if not installation.settings.matches(settings) or installation.source != source:
            raise ValueError(
                "This installation already exists with different settings. "
                "Use its lifecycle commands."
            )
    else:
        check_ports(settings)
        check_host(allow_unverified=arguments.allow_unverified_host)
        installation = Installation.create(arguments.home, source, settings)
    launcher = ManagedLauncher(installation)
    launcher.prepare(arguments.command_path, allow_alias=True)
    compose = Compose(installation)
    print(f"\nPAPILIO / {settings.environment} / {settings.instance}", flush=True)
    print("[1/5] Checking service configuration", flush=True)
    compose.run("config", "--quiet")
    print("[2/5] Preparing application images", flush=True)
    compose.run("build")
    print("[3/5] Starting PostgreSQL, Redis and RabbitMQ", flush=True)
    compose.run("up", "-d", "--wait", "postgres", "redis", "rabbitmq")
    print("[4/5] Applying database migrations", flush=True)
    compose.run("run", "--rm", "--no-deps", "api", "python", "manage.py", "migrate", "--noinput")
    print("[5/5] Starting the panel and verifying both worker queues", flush=True)
    compose.start()
    print(f"Open {settings.origin}/setup and enter the single-use token:")
    compose.run("exec", "-T", "api", "python", "manage.py", "owner_setup_token", "--if-needed")
    launcher.write(source)


def timestamped_backup(installation: Installation, prefix: str) -> Path:
    folder = installation.root / "backups"
    folder.mkdir(mode=0o700, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return folder / f"{prefix}-{timestamp}.tar.gz"


def update(installation: Installation, source: Path) -> None:
    launcher = ManagedLauncher(installation)
    launcher.prepare()
    source = source.resolve()
    if source == installation.source or not (source / "deployment/compose.yml").is_file():
        raise ValueError(
            "Extract the new release and provide its distinct directory with --source."
        )
    previous_version = (installation.source / "VERSION").read_text().strip()
    next_version = (source / "VERSION").read_text().strip()
    if previous_version == next_version:
        raise ValueError("The selected release is already installed.")
    backup_path = timestamped_backup(installation, "before-update")
    backup(installation, backup_path)
    next_installation = Installation(
        root=installation.root,
        source=source,
        settings=installation.settings,
        values=installation.values,
    )
    compose = Compose(next_installation)
    compose.run("config", "--quiet")
    compose.run("build")
    Compose(installation).stop()
    compose.run("up", "-d", "--wait", "postgres", "redis", "rabbitmq")
    compose.run("run", "--rm", "--no-deps", "api", "python", "manage.py", "migrate", "--noinput")
    metadata_path = installation.root / "installation.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["source"] = str(source)
    replace_private(metadata_path, json.dumps(metadata, indent=2) + "\n")
    compose.start()
    launcher.write(source)
    print(f"Updated to {next_version}. Recovery backup: {backup_path}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="papilio")
    root.add_argument("--home", type=Path, default=Path("/opt/papilio"))
    root.add_argument("--environment", choices=ENVIRONMENTS, default="sandbox")
    root.add_argument("--instance", default="default")
    commands = root.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("install")
    setup.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2])
    setup.add_argument("--settings-file", type=Path)
    setup.add_argument("--host")
    setup.add_argument("--scheme", choices=("http", "https"))
    setup.add_argument("--bind")
    setup.add_argument("--port", type=int)
    setup.add_argument("--https-port", type=int)
    setup.add_argument("--allow-unverified-host", action="store_true")
    setup.add_argument("--command-path", type=Path)
    for name in ("start", "stop", "restart", "status", "setup-token"):
        commands.add_parser(name)
    diagnostics = commands.add_parser("doctor")
    diagnostics.add_argument("--timeout", type=int, default=120)
    logs = commands.add_parser("logs")
    logs.add_argument("service", nargs="?")
    logs.add_argument("--tail", type=int, default=100)
    logs.add_argument("--follow", action="store_true")
    save = commands.add_parser("backup")
    save.add_argument("--output", type=Path)
    recover = commands.add_parser("restore")
    recover.add_argument("archive", type=Path)
    upgrade = commands.add_parser("update")
    upgrade.add_argument("--source", type=Path)
    upgrade.add_argument("--version")
    return root


def execute(arguments: argparse.Namespace) -> None:
    if arguments.command == "install":
        install(arguments)
        return
    installation = Installation.load(arguments.home / arguments.environment / arguments.instance)
    compose = Compose(installation)
    if arguments.command == "start":
        compose.start()
    elif arguments.command == "stop":
        compose.stop()
    elif arguments.command == "restart":
        compose.run("restart")
        compose.doctor()
    elif arguments.command == "status":
        compose.run("ps", "--all")
    elif arguments.command == "doctor":
        compose.doctor(arguments.timeout)
    elif arguments.command == "logs":
        flags = ["logs", "--tail", str(arguments.tail)]
        if arguments.follow:
            flags.append("--follow")
        if arguments.service:
            flags.append(arguments.service)
        compose.run(*flags)
    elif arguments.command == "setup-token":
        compose.run("exec", "-T", "api", "python", "manage.py", "owner_setup_token")
    elif arguments.command == "backup":
        destination = arguments.output or timestamped_backup(installation, "papilio")
        backup(installation, destination)
        print(destination)
    elif arguments.command == "restore":
        safety = timestamped_backup(installation, "before-restore")
        restore(installation, arguments.archive, safety)
        print(f"Restore finished. Pre-restore recovery backup: {safety}")
    elif arguments.command == "update":
        source = arguments.source or download_release(arguments.home, arguments.version)
        update(installation, source)


def main() -> None:
    arguments = parser().parse_args()
    try:
        execute(arguments)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Papilio could not finish: {error}", file=sys.stderr)
        sys.exit(1)
