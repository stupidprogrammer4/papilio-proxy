"""Prepare native binaries and private settings without resetting existing choices."""

import hashlib
import json
import os
import shutil
import ssl
import subprocess
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import UUID

from .artifacts import BUNDLE_FILES, BundleFile, NodeBundle
from .configuration import Bootstrap, NodeInstallSettings, seed_xray, service_unit, unit_path
from .packaging import bundle_metadata


@dataclass(frozen=True)
class NodeInstallation:
    root: Path
    node_id: UUID
    deployment_id: UUID
    version: str
    bootstrap_sha256: str
    settings: NodeInstallSettings
    platform: str
    files: dict[str, BundleFile]

    @property
    def service_name(self) -> str:
        return f"papilio-node-{self.settings.environment}-{self.node_id}.service"


def verify_installed_file(path: Path, expected: BundleFile) -> None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size != expected.size:
        raise ValueError("An installed native bundle file is missing or modified.")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1048576), b""):
            digest.update(block)
    if digest.hexdigest() != expected.sha256:
        raise ValueError("An installed native bundle file checksum has changed.")


def create_runtime_directories(path: Path) -> None:
    """Give newly owned binary directories traversal rights without changing existing parents."""
    for folder in reversed((path, *path.parents)):
        if not folder.exists():
            folder.mkdir(mode=0o755)
            folder.chmod(0o755)


def load_installation(root: Path) -> NodeInstallation:
    metadata = root / "installation.json"
    if root.is_symlink() or metadata.is_symlink() or not metadata.is_file():
        raise ValueError("The selected directory is not an owned Papilio node installation.")
    values = json.loads(metadata.read_text())
    if not isinstance(values, dict) or values.get("format") != 1:
        raise ValueError("The installed node metadata format is invalid.")
    settings = NodeInstallSettings(**values["settings"])
    settings.validate()
    files = values["bundle"]["files"]
    if set(files) != BUNDLE_FILES:
        raise ValueError("The installed node bundle metadata is incomplete.")
    for name, identity in files.items():
        verify_installed_file(root / name, BundleFile(**identity))
    return NodeInstallation(
        root,
        UUID(values["node_id"]),
        UUID(values["deployment_id"]),
        values["bundle"]["version"],
        values["bootstrap_sha256"],
        settings,
        values["bundle"]["platform"],
        {name: BundleFile(**identity) for name, identity in files.items()},
    )


def validate_native_files(staging: Path, timeout_seconds: int) -> None:
    credentials = staging / "credentials"
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(credentials / "server.crt", credentials / "server.key")
        context.load_verify_locations(cafile=str(credentials / "client-ca.crt"))
    except (OSError, ssl.SSLError) as error:
        raise ValueError(
            "The issued node certificate, private key or trust root is invalid."
        ) from error
    result = subprocess.run(
        [str(staging / "bin/xray"), "run", "-test", "-config", str(credentials / "xray.json")],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=timeout_seconds,
    )
    if result.returncode:
        raise ValueError("The native Xray executable rejected the selected seed configuration.")


def prepare_installation(
    root: Path, bundle: NodeBundle, bootstrap: Bootstrap, settings: NodeInstallSettings
) -> NodeInstallation:
    settings.validate()
    unit_path(root)
    expected = NodeInstallation(
        root,
        bootstrap.node_id,
        bootstrap.deployment_id,
        bundle.version,
        bootstrap.sha256,
        settings,
        bundle.platform,
        bundle.files,
    )
    if root.exists() or root.is_symlink():
        current = load_installation(root)
        if current != expected:
            raise ValueError(
                "This node already exists with different initial settings or release. "
                "Existing operator files were preserved."
            )
        return current
    xray_configuration = seed_xray(bootstrap, settings)
    unit = service_unit(root, bootstrap, settings)
    create_runtime_directories(root.parent)
    with tempfile.TemporaryDirectory(prefix=".node-stage-", dir=root.parent) as temporary:
        staging = Path(temporary) / "instance"
        staging.mkdir(mode=0o755)
        staging.chmod(0o755)
        with tarfile.open(bundle.path, "r:gz") as archive:
            for name, identity in bundle.files.items():
                member = archive.getmember(name)
                if not member.isfile():
                    raise ValueError("The node bundle changed after validation.")
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError("A native bundle file disappeared after validation.")
                destination = staging / name
                create_runtime_directories(destination.parent)
                with source, destination.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1048576)
                verify_installed_file(destination, identity)
                destination.chmod(0o755 if name.startswith("bin/") else 0o644)
        credentials = staging / "credentials"
        credentials.mkdir(mode=0o700)
        agent_configuration = bootstrap.runtime | {
            "managed_xray": {
                "binary_file": str(root / "bin/xray"),
                "configuration_file": "xray.json",
            }
        }
        private_files = bootstrap.files | {
            "agent.json": json.dumps(agent_configuration, indent=2).encode(),
            "xray.json": json.dumps(xray_configuration, indent=2).encode(),
        }
        for name, content in private_files.items():
            path = credentials / name
            with path.open("xb") as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(content)
        validate_native_files(staging, bootstrap.runtime["shutdown_timeout_seconds"])
        (staging / expected.service_name).write_text(unit)
        metadata = {
            "format": 1,
            "node_id": str(bootstrap.node_id),
            "deployment_id": str(bootstrap.deployment_id),
            "bootstrap_sha256": bootstrap.sha256,
            "settings": asdict(settings),
            "bundle": bundle_metadata(bundle),
        }
        with (staging / "installation.json").open("x") as output:
            os.fchmod(output.fileno(), 0o600)
            json.dump(metadata, output, indent=2)
        staging.rename(root)
    return expected
