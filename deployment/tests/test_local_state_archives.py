"""Local runtime archive shapes reject links, traversal and mismatched ownership."""

import io
import json
import tarfile
from pathlib import Path
from uuid import uuid4

import pytest
from deployment.papilio_installer.archives import inspect_archive


def local_archive(path: Path, *, extra: str | None = None, symlink: bool = False) -> None:
    marker = json.dumps(
        {"version": 1, "node_id": str(uuid4()), "deployment_id": str(uuid4())}
    ).encode()
    names = {
        "agent.json": b"{}",
        "xray.json": b"{}",
        "server.crt": b"private-cert",
        "server.key": b"private-key",
        "client-ca.crt": b"private-ca",
        "papilio.json": marker,
    }
    with tarfile.open(path, "w") as archive:
        for name, value in names.items():
            row = tarfile.TarInfo("instance/" + name)
            row.size, row.mode = len(value), 0o600
            archive.addfile(row, io.BytesIO(value))
        if extra:
            row = tarfile.TarInfo(extra)
            if symlink:
                row.type, row.linkname = tarfile.SYMTYPE, "/etc/passwd"
            archive.addfile(row)


def test_local_archive_describes_complete_state_and_keeps_operator_files(tmp_path: Path) -> None:
    from deployment.papilio_installer.local_state import inspect_local_state

    path = tmp_path / "local.tar"
    local_archive(path, extra="instance/operator-note.txt")
    result = inspect_local_state(path)
    assert result.present and result.node_id is not None and result.deployment_id is not None
    empty = tmp_path / "empty.tar"
    with tarfile.open(empty, "w"):
        pass
    assert inspect_local_state(empty).present is False


@pytest.mark.parametrize(
    "name,symlink",
    [
        ("../outside", False),
        ("/etc/passwd", False),
        ("instance/../../outside", False),
        ("foreign/file", False),
        ("instance/link", True),
        ("instance/server.key", False),
    ],
)
def test_local_archive_rejects_unsafe_or_duplicate_members(
    tmp_path: Path,
    name: str,
    symlink: bool,
) -> None:
    from deployment.papilio_installer.local_state import inspect_local_state

    path = tmp_path / "unsafe.tar"
    local_archive(path, extra=name, symlink=symlink)
    with pytest.raises(ValueError):
        inspect_local_state(path)


@pytest.mark.parametrize(
    "version,declared,included,valid",
    [
        (2, True, True, True),
        (2, False, False, True),
        (2, True, False, False),
        (2, False, True, False),
        (2, None, False, False),
        (2, 1, True, False),
        (1, True, True, False),
        (True, False, False, False),
    ],
)
def test_outer_backup_requires_an_explicit_consistent_local_snapshot_declaration(
    tmp_path: Path,
    version: int,
    declared: object,
    included: bool,
    valid: bool,
) -> None:
    path = tmp_path / "outer.tar"
    supplied = {
        "manifest.json": json.dumps({"format": version, "local_node": declared}).encode(),
        "database.dump": b"component-test-dump",
        "runtime.env": b"PAPILIO_ENV='test'\n",
    }
    if included:
        supplied["local-node.tar"] = b"nested-content-is-validated-by-restore"
    with tarfile.open(path, "w") as archive:
        for name, content in supplied.items():
            row = tarfile.TarInfo(name)
            row.size = len(content)
            archive.addfile(row, io.BytesIO(content))
    if valid:
        assert inspect_archive(path)["local_node"] == declared
    else:
        with pytest.raises(ValueError):
            inspect_archive(path)
