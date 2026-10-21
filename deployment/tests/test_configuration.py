"""Installer settings must isolate instances and protect existing installations."""

import os
import socket
from pathlib import Path

import pytest
from deployment.papilio_installer.configuration import Installation, InstallSettings, decode_env
from deployment.papilio_installer.preflight import check_ports


def test_environments_have_distinct_projects_paths_and_credentials(tmp_path: Path) -> None:
    installations = [
        Installation.create(
            tmp_path, Path.cwd(), InstallSettings(environment=environment, instance="first")
        )
        for environment in ("dev", "test", "sandbox", "production")
    ]
    assert len({item.root for item in installations}) == 4
    assert len({item.settings.project for item in installations}) == 4
    assert len({item.values["PAPILIO_SECRET_KEY"] for item in installations}) == 4
    for item in installations:
        assert (item.root / "runtime.env").stat().st_mode & 0o777 == 0o600
        assert item.root.stat().st_mode & 0o777 == 0o700
        assert item.values["DATABASE_URL"].startswith("postgresql://papilio:")
        assert item.values["PAPILIO_ENV"] == item.settings.environment
        assert Installation.load(item.root).values == item.values


@pytest.mark.parametrize("instance", ["../escape", "A", "", "x\nKEY=bad", "/tmp/other"])
def test_invalid_identity_creates_no_files(tmp_path: Path, instance: str) -> None:
    with pytest.raises(ValueError):
        Installation.create(tmp_path, Path.cwd(), InstallSettings(instance=instance))
    assert not list(tmp_path.iterdir())


def test_install_refuses_to_overwrite_existing_secrets(tmp_path: Path) -> None:
    settings = InstallSettings()
    original = Installation.create(tmp_path, Path.cwd(), settings)
    with pytest.raises(FileExistsError):
        Installation.create(tmp_path, Path.cwd(), settings)
    assert Installation.load(original.root).values == original.values


def test_occupied_port_is_rejected_before_installation_changes(tmp_path: Path) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        settings = InstallSettings(http_port=port)
        with pytest.raises(ValueError, match="port"):
            check_ports(settings)
    assert not list(tmp_path.iterdir())


def test_source_paths_are_data_and_never_evaluated(tmp_path: Path) -> None:
    source = tmp_path / "source with $literal and 'quotes'"
    item = Installation.create(tmp_path / "install", source, InstallSettings())
    assert Installation.load(item.root).source == source.resolve()
    assert "$(" not in item.values["PAPILIO_SECRET_KEY"]
    assert os.stat(item.root / "installation.json").st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "name", ["PATH", "PYTHONPATH", "LD_PRELOAD", "DOCKER_HOST", "COMPOSE_FILE"]
)
def test_imported_settings_cannot_change_host_execution(name: str) -> None:
    with pytest.raises(ValueError):
        decode_env(f"{name}='/attacker'\n")


def test_loaded_state_paths_cannot_escape_the_installation(tmp_path: Path) -> None:
    installation = Installation.create(tmp_path, Path.cwd(), InstallSettings())
    path = installation.root / "runtime.env"
    path.write_text(path.read_text().replace(installation.values["PAPILIO_STATE_ROOT"], "/etc"))
    with pytest.raises(ValueError):
        Installation.load(installation.root)
