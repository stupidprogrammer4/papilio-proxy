"""Downloaded source archives never escape their release directory."""

import io
import tarfile
from pathlib import Path

import pytest
from deployment.papilio_installer.releases import extract_release


def test_valid_release_is_extracted_with_executable_modes(tmp_path: Path) -> None:
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        for name, content in {
            "VERSION": b"0.1.0-alpha.1\n",
            "deployment/compose.yml": b"services: {}\n",
            "install.sh": b"#!/bin/sh\n",
        }.items():
            member = tarfile.TarInfo(f"papilio-0.1.0-alpha.1/{name}")
            member.size = len(content)
            member.mode = 0o755 if name == "install.sh" else 0o644
            output.addfile(member, io.BytesIO(content))
    source = extract_release(archive, tmp_path / "releases", "0.1.0-alpha.1")
    assert (source / "VERSION").read_text().strip() == "0.1.0-alpha.1"
    assert (source / "install.sh").stat().st_mode & 0o111


def test_release_rejects_symlink_and_parent_escape(tmp_path: Path) -> None:
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        row = tarfile.TarInfo("papilio-0.1.0-alpha.1/../../escaped")
        row.size = 1
        output.addfile(row, io.BytesIO(b"x"))
    with pytest.raises(ValueError):
        extract_release(archive, tmp_path / "releases", "0.1.0-alpha.1")
    assert not (tmp_path / "escaped").exists()
