"""Private backups and validated native PostgreSQL restore boundaries."""

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .configuration import Installation, decode_env, encode_env, replace_private
from .docker import Compose
from .local_state import inspect_local_state, restore_local_state, snapshot_local_state

REQUIRED = {"manifest.json", "database.dump", "runtime.env"}
APPLICATION_SERVICES = ("gateway", "beat", "worker-io", "worker-cpu", "api", "local-node")


@contextmanager
def snapshot_window(compose: Compose) -> Iterator[None]:
    running: tuple[str, ...] = ()
    if compose.installation.settings.local_node:
        current = (
            compose.run("ps", "--status", "running", "--services", capture=True)
            .stdout.decode()
            .split()
        )
        running = tuple(name for name in APPLICATION_SERVICES if name in current)
    try:
        if running:
            compose.run(
                "stop",
                "--timeout",
                compose.installation.values["PAPILIO_SHUTDOWN_SECONDS"],
                *running,
            )
        yield
    finally:
        if running:
            compose.run("start", *running)


def database_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_archive(path: Path) -> dict[str, object]:
    seen = set()
    with tarfile.open(path, "r:*") as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or member.name in seen:
                raise ValueError("Unsafe or duplicate backup member.")
            if not member.isfile() and not member.isdir():
                raise ValueError("Backup links and special files are not accepted.")
            if member.name not in REQUIRED | {"certificates.tar", "local-node.tar"}:
                raise ValueError("Unexpected backup member.")
            seen.add(member.name)
        if not REQUIRED.issubset(seen):
            raise ValueError("The backup is incomplete.")
        manifest_file = archive.extractfile("manifest.json")
        if manifest_file is None:
            raise ValueError("The backup manifest is missing.")
        manifest = json.load(manifest_file)
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("format")) is not int
        or manifest.get("format") not in (1, 2)
    ):
        raise ValueError("Unsupported backup format.")
    if manifest["format"] == 2 and (
        type(manifest.get("local_node")) is not bool
        or manifest["local_node"] != ("local-node.tar" in seen)
    ):
        raise ValueError("The backup local runtime declaration is inconsistent.")
    if manifest["format"] == 1 and "local-node.tar" in seen:
        raise ValueError("Legacy backups cannot declare a local runtime snapshot.")
    return manifest


def backup(installation: Installation, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError("Choose a new backup filename.")
    compose = Compose(installation)
    with (
        snapshot_window(compose),
        tempfile.TemporaryDirectory(prefix="papilio-backup-") as temporary,
    ):
        folder = Path(temporary)
        dump = folder / "database.dump"
        with dump.open("wb") as output:
            compose.run(
                "exec",
                "-T",
                "postgres",
                "pg_dump",
                "--username=papilio",
                "--dbname=papilio",
                "--format=custom",
                "--no-owner",
                "--no-acl",
                stdout=output,
            )
        manifest = {
            "format": 2 if installation.settings.local_node else 1,
            "local_node": installation.settings.local_node,
            "postgres_major": 17,
            "version": (installation.source / "VERSION").read_text().strip(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "environment": installation.settings.environment,
            "instance": installation.settings.instance,
            "database_sha256": database_digest(dump),
        }
        local_state = folder / "local-node.tar"
        if installation.settings.local_node:
            snapshot_local_state(compose, local_state)
            manifest["local_node_sha256"] = database_digest(local_state)
        manifest_path = folder / "manifest.json"
        manifest_path.write_text(json.dumps(manifest))
        certificates = folder / "certificates.tar"
        with certificates.open("wb") as output:
            if installation.settings.local_node:
                compose.run(
                    "run",
                    "-T",
                    "--rm",
                    "--no-deps",
                    "--entrypoint",
                    "tar",
                    "gateway",
                    "-C",
                    "/data",
                    "-cf",
                    "-",
                    ".",
                    stdout=output,
                )
            else:
                compose.run(
                    "exec", "-T", "gateway", "tar", "-C", "/data", "-cf", "-", ".", stdout=output
                )
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with (
            os.fdopen(descriptor, "wb") as output,
            tarfile.open(fileobj=output, mode="w:gz") as archive,
        ):
            archive.add(manifest_path, arcname="manifest.json")
            archive.add(dump, arcname="database.dump")
            archive.add(installation.root / "runtime.env", arcname="runtime.env")
            archive.add(certificates, arcname="certificates.tar")
            if installation.settings.local_node:
                archive.add(local_state, arcname="local-node.tar")


def restore(installation: Installation, source: Path, safety_backup: Path) -> None:
    manifest = inspect_archive(source)
    current_version = (installation.source / "VERSION").read_text().strip()
    if manifest.get("postgres_major") != 17 or manifest.get("version") != current_version:
        raise ValueError("Restore requires PostgreSQL 17 and the same application release.")
    if (manifest.get("environment"), manifest.get("instance")) != (
        installation.settings.environment,
        installation.settings.instance,
    ):
        raise ValueError("Restore requires matching environment and instance identities.")
    if bool(manifest.get("local_node", False)) != installation.settings.local_node:
        raise ValueError("Restore requires matching local runtime installation settings.")
    with tempfile.TemporaryDirectory(prefix="papilio-restore-") as temporary:
        folder = Path(temporary)
        with tarfile.open(source, "r:*") as archive:
            for filename in REQUIRED | {"certificates.tar", "local-node.tar"}:
                if filename not in archive.getnames():
                    continue
                member = archive.extractfile(filename)
                if member is None:
                    raise ValueError("Backup data is missing.")
                with member, (folder / filename).open("wb") as output:
                    shutil.copyfileobj(member, output)
        dump = folder / "database.dump"
        if database_digest(dump) != manifest.get("database_sha256"):
            raise ValueError("The database checksum does not match the manifest.")
        local_state = folder / "local-node.tar"
        if installation.settings.local_node:
            if database_digest(local_state) != manifest.get("local_node_sha256"):
                raise ValueError("The local runtime checksum does not match the manifest.")
            inspect_local_state(local_state)
        certificates = folder / "certificates.tar"
        if certificates.exists():
            with tarfile.open(certificates) as archive:
                for member in archive:
                    path = PurePosixPath(member.name)
                    if (
                        path.is_absolute()
                        or ".." in path.parts
                        or not (member.isfile() or member.isdir())
                    ):
                        raise ValueError("Unsafe certificate archive.")
        previous_values = decode_env((folder / "runtime.env").read_text())
        if not previous_values.get("PAPILIO_SECRET_KEY"):
            raise ValueError("The backup has no application signing key.")
        backup(installation, safety_backup)
        compose = Compose(installation)
        compose.run(
            "stop",
            "--timeout",
            installation.values["PAPILIO_SHUTDOWN_SECONDS"],
            "gateway",
            "beat",
            "worker-io",
            "worker-cpu",
            "api",
            *(("local-node",) if installation.settings.local_node else ()),
        )
        with dump.open("rb") as input_file:
            compose.run(
                "exec",
                "-T",
                "postgres",
                "pg_restore",
                "--username=papilio",
                "--dbname=papilio",
                "--single-transaction",
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-acl",
                stdin=input_file,
            )
        # Restore app settings; keep destination infrastructure credentials and addresses.
        retained = {
            key: value
            for key, value in installation.values.items()
            if key
            in {
                "DATABASE_URL",
                "POSTGRES_PASSWORD",
                "PAPILIO_DB_PASSWORD",
                "PAPILIO_CACHE_URL",
                "PAPILIO_REDIS_PASSWORD",
                "REDISCLI_AUTH",
                "CELERY_BROKER_URL",
                "RABBITMQ_DEFAULT_USER",
                "RABBITMQ_DEFAULT_PASS",
                "PAPILIO_PROJECT",
                "PAPILIO_STATE_ROOT",
                "PAPILIO_ENV_FILE",
                "PAPILIO_BIND_ADDRESS",
                "PAPILIO_HTTP_PORT",
                "PAPILIO_HTTPS_PORT",
                "PAPILIO_SITE_ADDRESS",
                "PAPILIO_ALLOWED_HOSTS",
                "PAPILIO_TRUSTED_ORIGINS",
                "PAPILIO_TRANSPORT_SCHEME",
                "PAPILIO_SESSION_COOKIE_SECURE",
                "PAPILIO_CSRF_COOKIE_SECURE",
                "PAPILIO_SECURE_SSL_REDIRECT",
                "PAPILIO_LOCAL_NODE_AVAILABLE",
                "PAPILIO_LOCAL_NODE_PUBLIC_HOST",
                "PAPILIO_LOCAL_NODE_PUBLIC_PORT",
                "PAPILIO_NODE_PORT",
                "PAPILIO_LOCAL_NODE_STATE_ROOT",
            }
        }
        restored_values = previous_values | retained
        env_file = installation.root / "runtime.env"
        replace_private(env_file, encode_env(restored_values))
        updated = Installation.load(installation.root)
        compose = Compose(updated)
        if installation.settings.local_node:
            restore_local_state(compose, local_state)
        if certificates.exists():
            with certificates.open("rb") as input_file:
                compose.run(
                    "run",
                    "--rm",
                    "--no-deps",
                    "--entrypoint",
                    "tar",
                    "gateway",
                    "-C",
                    "/data",
                    "-xf",
                    "-",
                    stdin=input_file,
                )
        # The DB outbox is authoritative; remove this instance's stale broker deliveries.
        compose.run(
            "run",
            "--rm",
            "--no-deps",
            "api",
            "celery",
            "-A",
            "papilio_panel.config.celery:app",
            "purge",
            "--force",
        )
        compose.start()
