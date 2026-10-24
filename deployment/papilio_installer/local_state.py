"""Native private-volume snapshots and validated local runtime restore."""

import json
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID

from .docker import Compose

REQUIRED_FILES = frozenset(
    {"agent.json", "xray.json", "server.crt", "server.key", "client-ca.crt", "papilio.json"}
)


@dataclass(frozen=True)
class LocalStateRead:
    present: bool
    node_id: UUID | None = None
    deployment_id: UUID | None = None


def inspect_local_state(path: Path) -> LocalStateRead:
    files, seen = set(), set()
    with tarfile.open(path, "r:*") as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            normalized = str(name)
            if (
                name.is_absolute()
                or ".." in name.parts
                or not name.parts
                or name.parts[0] != "instance"
                or normalized in seen
                or not (member.isfile() or member.isdir())
            ):
                raise ValueError("The local runtime archive contains an unsafe member.")
            seen.add(normalized)
            if member.isfile():
                files.add(normalized)
        if not seen:
            return LocalStateRead(False)
        if not {f"instance/{name}" for name in REQUIRED_FILES}.issubset(files):
            raise ValueError("The local runtime snapshot is incomplete.")
        marker = archive.getmember("instance/papilio.json")
        if marker.size > 4096:
            raise ValueError("The local runtime ownership marker is invalid.")
        stream = archive.extractfile(marker)
        if stream is None:
            raise ValueError("The local runtime ownership marker is missing.")
        try:
            identity = json.load(stream)
            if (
                not isinstance(identity, dict)
                or type(identity.get("version")) is not int
                or identity["version"] != 1
            ):
                raise ValueError("Unsupported local runtime snapshot identity.")
            result = LocalStateRead(
                True, UUID(identity["node_id"]), UUID(identity["deployment_id"])
            )
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise ValueError("The local runtime ownership marker is invalid.") from error
    return result


# This helper runs as UID10001 in the existing IO service's project-scoped volume.
# It does not receive Docker/systemd access or a caller-selected filesystem root.
PRIVATE_ROOT = """
base = Path("/var/lib/papilio/local-node")
root = Path(os.environ.get("PAPILIO_LOCAL_NODE_STATE_ROOT", str(base)))
if not root.is_absolute() or root.resolve() != root or not root.is_relative_to(base):
    raise ValueError("The local runtime root is outside its private volume.")
root.mkdir(mode=0o700, parents=True, exist_ok=True)
target = root / "instance"
if target.is_symlink() or (target.exists() and not target.is_dir()):
    raise ValueError("The local runtime target requires operator review.")
"""

SNAPSHOT = (
    """
import os
import sys
import tarfile
from pathlib import Path
"""
    + PRIVATE_ROOT
    + """
with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
    if target.exists():
        archive.add(target, arcname="instance")
"""
)

RESTORE = (
    """
import json
import os
import sys
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID
"""
    + PRIVATE_ROOT
    + """
if target.exists():
    marker = target / "papilio.json"
    if marker.is_symlink() or not marker.is_file():
        raise ValueError("The existing local runtime is not recognized.")
    identity = json.loads(marker.read_bytes())
    if identity.get("version") != 1:
        raise ValueError("The existing local runtime ownership marker is invalid.")
    UUID(identity["node_id"])
    UUID(identity["deployment_id"])
with TemporaryDirectory(prefix=".restore-", dir=root) as temporary:
    staging = Path(temporary)
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|*") as archive:
        archive.extractall(staging, filter="data")
    prepared, previous = staging / "instance", staging / "previous"
    if prepared.exists():
        prepared.chmod(0o700)
    if target.exists():
        os.rename(target, previous)
    try:
        if prepared.exists():
            os.rename(prepared, target)
    except OSError:
        if previous.exists() and not target.exists():
            os.rename(previous, target)
        raise
"""
)


def snapshot_local_state(compose: Compose, destination: Path) -> None:
    with destination.open("wb") as output:
        compose.run(
            "run",
            "-T",
            "--rm",
            "--no-deps",
            "--entrypoint",
            "python",
            "worker-io",
            "-c",
            SNAPSHOT,
            stdout=output,
        )
    inspect_local_state(destination)


def restore_local_state(compose: Compose, source: Path) -> None:
    inspect_local_state(source)
    with source.open("rb") as input_file:
        compose.run(
            "run",
            "-T",
            "--rm",
            "--no-deps",
            "--entrypoint",
            "python",
            "worker-io",
            "-c",
            RESTORE,
            stdin=input_file,
        )
