"""Reject unsafe restore archives before any Docker or database operation."""

import io
import json
import subprocess
import tarfile
from pathlib import Path
from typing import Any

import pytest
from deployment.papilio_installer.archives import backup, inspect_archive
from deployment.papilio_installer.configuration import Installation, InstallSettings


@pytest.mark.parametrize("name", ["../outside", "/etc/passwd", "state/../../outside"])
def test_restore_rejects_path_escape(tmp_path: Path, name: str) -> None:
    archive = tmp_path / "hostile.tar"
    with tarfile.open(archive, "w") as output:
        row = tarfile.TarInfo(name)
        row.size = 4
        output.addfile(row, io.BytesIO(b"evil"))
    with pytest.raises(ValueError):
        inspect_archive(archive)


def test_restore_rejects_links_and_duplicate_members(tmp_path: Path) -> None:
    archive = tmp_path / "hostile.tar"
    with tarfile.open(archive, "w") as output:
        row = tarfile.TarInfo("database.dump")
        row.type = tarfile.SYMTYPE
        row.linkname = "/etc/passwd"
        output.addfile(row)
    with pytest.raises(ValueError):
        inspect_archive(archive)


def test_nonlocal_backup_keeps_the_legacy_format_with_external_command_doubles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "VERSION").write_text("0.1.0-alpha.3\n")
    installation = Installation.create(
        tmp_path / "home", source, InstallSettings(image_mode="build")
    )

    def external_command(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        kwargs["stdout"].write(b"controlled-external-backup-content")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", external_command)
    saved = tmp_path / "backup.tar.gz"
    backup(installation, saved)
    with tarfile.open(saved) as archive:
        stream = archive.extractfile("manifest.json")
        assert stream is not None
        assert json.load(stream)["format"] == 1
        assert "local-node.tar" not in archive.getnames()
