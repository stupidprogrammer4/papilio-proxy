"""Installed commands preserve unrelated files and follow the selected release."""

import subprocess
from pathlib import Path

import pytest
from deployment.papilio_installer.configuration import Installation, InstallSettings
from deployment.papilio_installer.launcher import ManagedLauncher


def test_launcher_refuses_existing_unowned_file(tmp_path: Path) -> None:
    installation = Installation.create(tmp_path / "home", tmp_path / "source", InstallSettings())
    path = tmp_path / "papilio"
    path.write_text("unrelated command\n")
    with pytest.raises(ValueError, match="owned"):
        ManagedLauncher(installation).prepare(path)
    assert path.read_text() == "unrelated command\n"


def test_launcher_tracks_new_release_and_preserves_modified_command(tmp_path: Path) -> None:
    first = tmp_path / "first source"
    second = tmp_path / "next source"
    for source, version in ((first, "first"), (second, "next")):
        (source / "deployment").mkdir(parents=True)
        (source / "deployment/papilio.py").write_text(f"print('{version}')\n")
    installation = Installation.create(tmp_path / "home", first, InstallSettings())
    path = tmp_path / "commands/papilio"
    launcher = ManagedLauncher(installation)
    launcher.prepare(path)
    launcher.write(first)
    assert subprocess.check_output([str(path)], text=True).strip() == "first"
    reloaded = ManagedLauncher(Installation.load(installation.root))
    reloaded.prepare()
    reloaded.write(second)
    assert subprocess.check_output([str(path)], text=True).strip() == "next"
    path.write_text("edited by operator\n")
    with pytest.raises(ValueError, match="modified"):
        ManagedLauncher(Installation.load(installation.root)).prepare()
    assert path.read_text() == "edited by operator\n"


def test_launcher_refuses_symlink_even_when_target_matches(tmp_path: Path) -> None:
    installation = Installation.create(tmp_path / "home", tmp_path / "source", InstallSettings())
    target = tmp_path / "target"
    target.write_text("unrelated")
    path = tmp_path / "papilio"
    path.symlink_to(target)
    with pytest.raises(ValueError):
        ManagedLauncher(installation).prepare(path)
    assert target.read_text() == "unrelated"


def test_second_instance_gets_distinct_command_without_replacing_first(tmp_path: Path) -> None:
    first = Installation.create(tmp_path / "home", tmp_path / "source", InstallSettings())
    second = Installation.create(
        tmp_path / "home", tmp_path / "source", InstallSettings(environment="test")
    )
    path = tmp_path / "bin/papilio"
    launcher = ManagedLauncher(first)
    launcher.prepare(path)
    launcher.write(first.source)
    original = path.read_bytes()
    other = ManagedLauncher(second)
    other.prepare(path, allow_alias=True)
    other.write(second.source)
    assert other.path == path.with_name("papilio-default-test")
    assert path.read_bytes() == original
