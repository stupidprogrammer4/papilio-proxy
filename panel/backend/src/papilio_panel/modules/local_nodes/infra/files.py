"""Publish a private runtime directory atomically without replacing operator state."""

import errno
import io
import json
import os
import stat
import zipfile
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage

from papilio_panel.shared.errors import Conflict, InvalidInput

from ..domain import LocalBootstrap

BOOTSTRAP_FILES = frozenset({"agent.json", "server.crt", "server.key", "client-ca.crt"})
INSTANCE_FILES = BOOTSTRAP_FILES | {"xray.json", "papilio.json"}
BOOTSTRAP_BYTE_LIMIT = 1048576


def private_archive(values: LocalBootstrap) -> dict[str, bytes]:
    if len(values.archive) > BOOTSTRAP_BYTE_LIMIT:
        raise InvalidInput("The local bootstrap archive exceeds its transport limit.")
    try:
        with zipfile.ZipFile(io.BytesIO(values.archive)) as archive:
            members = archive.infolist()
            if (
                len(members) != len(BOOTSTRAP_FILES)
                or {row.filename for row in members} != BOOTSTRAP_FILES
                or sum(row.file_size for row in members) > BOOTSTRAP_BYTE_LIMIT
                or any(
                    row.is_dir()
                    or row.flag_bits & 1
                    or stat.S_IFMT(row.external_attr >> 16) not in (0, stat.S_IFREG)
                    for row in members
                )
            ):
                raise InvalidInput("The local bootstrap archive has invalid members.")
            files = {row.filename: archive.read(row) for row in members}
        configuration = json.loads(files["agent.json"])
        if not isinstance(configuration, dict) or any(
            configuration.get(name) != expected
            for name, expected in (
                ("node_id", str(values.node.id)),
                ("deployment_id", str(values.node.deployment_id)),
                ("tls_certificate_file", "server.crt"),
                ("tls_key_file", "server.key"),
                ("client_ca_file", "client-ca.crt"),
            )
        ):
            raise InvalidInput("The local bootstrap identity or credential paths are invalid.")
    except (zipfile.BadZipFile, UnicodeError, ValueError, RuntimeError, OSError) as error:
        raise InvalidInput("The local bootstrap archive cannot be read.") from error
    return files


def ownership(values: LocalBootstrap) -> dict[str, str | int]:
    return {
        "version": 1,
        "node_id": str(values.node.id),
        "deployment_id": str(values.node.deployment_id),
    }


def seed_configuration(values: LocalBootstrap) -> dict[str, Any]:
    selected = values.definition
    return {
        "log": {"loglevel": "warning"},
        "api": {
            "tag": "management",
            "listen": values.node.runtime.xray_api_address,
            "services": ["HandlerService", "StatsService"],
        },
        "stats": {},
        "inbounds": [
            {
                "tag": selected.inbound_tag,
                "listen": selected.bind_address,
                "port": selected.bind_port,
                "protocol": "vless",
                "settings": {"clients": [], "decryption": "none"},
            }
        ],
        "outbounds": [{"protocol": "freedom", "tag": "direct"}],
    }


def existing_instance(target: Path, values: LocalBootstrap) -> bool:
    if not target.exists() and not target.is_symlink():
        return False
    if target.is_symlink() or not target.is_dir():
        raise Conflict("The local runtime path belongs to another resource.")
    if any(
        (target / name).is_symlink() or not (target / name).is_file() for name in INSTANCE_FILES
    ):
        raise Conflict("The existing local runtime files require operator review.")
    try:
        marker = json.loads((target / "papilio.json").read_bytes())
        agent = json.loads((target / "agent.json").read_bytes())
    except (ValueError, OSError) as error:
        raise Conflict("The existing local runtime identity cannot be read.") from error
    if (
        marker != ownership(values)
        or not isinstance(agent, dict)
        or (
            agent.get("node_id") != str(values.node.id)
            or agent.get("deployment_id") != str(values.node.deployment_id)
        )
    ):
        raise Conflict("The existing local runtime identity does not match this installation.")
    return True


class NativeLocalFiles:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root

    def publish(self, values: LocalBootstrap) -> None:
        root = self.root or Path(settings.PAPILIO_LOCAL_NODE_STATE_ROOT)
        if not root.is_absolute() or root.resolve() != root or root.is_symlink():
            raise InvalidInput("The local runtime requires an absolute private directory.")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = root / "instance"
        if existing_instance(target, values):
            return
        files = private_archive(values)
        agent = asdict(values.node.runtime) | {
            "node_id": str(values.node.id),
            "deployment_id": str(values.node.deployment_id),
            "tls_certificate_file": "server.crt",
            "tls_key_file": "server.key",
            "client_ca_file": "client-ca.crt",
            "managed_xray": {
                "binary_file": settings.PAPILIO_LOCAL_XRAY_BINARY,
                "configuration_file": "xray.json",
            },
        }
        files["agent.json"] = json.dumps(agent, indent=2).encode()
        files["xray.json"] = json.dumps(seed_configuration(values), indent=2).encode()
        files["papilio.json"] = json.dumps(ownership(values), indent=2).encode()
        with TemporaryDirectory(prefix=".prepare-", dir=root) as temporary:
            staged = Path(temporary) / "instance"
            staged.mkdir(mode=0o700)
            storage = FileSystemStorage(
                location=staged, file_permissions_mode=0o600, directory_permissions_mode=0o700
            )
            for name, content in files.items():
                storage.save(name, ContentFile(content))
            try:
                os.rename(staged, target)
            except OSError as error:
                if error.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                    raise
                existing_instance(target, values)
