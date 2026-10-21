"""Reject unsafe restore archives before any Docker or database operation."""

import io
import tarfile
from pathlib import Path

import pytest
from deployment.papilio_installer.archives import inspect_archive


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
