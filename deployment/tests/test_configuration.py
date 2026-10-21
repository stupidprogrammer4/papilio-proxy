"""Installer settings must isolate instances and protect existing installations."""

import json
import os
import socket
from pathlib import Path

import pytest
from deployment.papilio_installer.cli import install, parser
from deployment.papilio_installer.configuration import (
    Installation,
    InstallSettings,
    decode_env,
    encode_env,
)
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


@pytest.mark.parametrize("environment", ["dev", "test", "sandbox", "production"])
@pytest.mark.parametrize("scheme", ["http", "https"])
def test_transport_is_independent_of_environment(
    tmp_path: Path, environment: str, scheme: str
) -> None:
    settings = InstallSettings(environment=environment, scheme=scheme, host="panel.test")
    installation = Installation.create(tmp_path, Path.cwd(), settings)
    port = settings.https_port if scheme == "https" else settings.http_port
    assert settings.tls_enabled == (scheme == "https")
    assert settings.origin == f"{scheme}://panel.test:{port}"
    assert installation.values["PAPILIO_TRANSPORT_SCHEME"] == scheme
    assert installation.values["PAPILIO_TRUSTED_ORIGINS"] == settings.origin
    assert installation.values["PAPILIO_SITE_ADDRESS"] == (
        "panel.test" if scheme == "https" else ":80"
    )
    assert Installation.load(installation.root).settings == settings


@pytest.mark.parametrize("environment", ["dev", "test", "sandbox", "production"])
def test_old_metadata_retains_transport_and_secrets(tmp_path: Path, environment: str) -> None:
    installation = Installation.create(
        tmp_path, Path.cwd(), InstallSettings(environment=environment)
    )
    path = installation.root / "installation.json"
    metadata = json.loads(path.read_text())
    metadata["settings"].pop("scheme", None)
    path.write_text(json.dumps(metadata))
    legacy_values = {
        key: value
        for key, value in installation.values.items()
        if key != "PAPILIO_TRANSPORT_SCHEME"
    }
    (installation.root / "runtime.env").write_text(encode_env(legacy_values))
    reloaded = Installation.load(installation.root)
    assert reloaded.settings.tls_enabled == (environment == "production")
    assert reloaded.values == legacy_values


def test_production_http_does_not_reserve_an_unused_https_port() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        occupied = listener.getsockname()[1]
        with socket.socket() as available:
            available.bind(("127.0.0.1", 0))
            port = available.getsockname()[1]
        check_ports(
            InstallSettings(
                environment="production", scheme="http", http_port=port, https_port=occupied
            )
        )


def test_nonproduction_https_checks_both_ports() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with pytest.raises(ValueError, match="port"):
            check_ports(InstallSettings(scheme="https", https_port=listener.getsockname()[1]))


@pytest.mark.parametrize("scheme", ["ftp", "HTTP", "", "https\nBAD=value"])
def test_invalid_transport_creates_no_files(tmp_path: Path, scheme: str) -> None:
    with pytest.raises(ValueError, match="scheme"):
        Installation.create(tmp_path, Path.cwd(), InstallSettings(scheme=scheme))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("environment", ["dev", "test", "sandbox", "production"])
def test_explicit_legacy_scheme_matches_existing_configuration(environment: str) -> None:
    legacy = InstallSettings(environment=environment)
    explicit = InstallSettings(environment=environment, scheme=legacy.transport_scheme)
    assert legacy.matches(explicit)
    assert explicit.matches(legacy)
    opposite = InstallSettings(
        environment=environment, scheme="http" if legacy.tls_enabled else "https"
    )
    assert not legacy.matches(opposite)


@pytest.mark.parametrize("flag", ["--port", "--https-port"])
def test_cli_rejects_port_zero_before_creating_state(tmp_path: Path, flag: str) -> None:
    arguments = parser().parse_args(
        [
            "--home",
            str(tmp_path / "install"),
            "--environment",
            "production",
            "install",
            "--source",
            str(Path(__file__).resolve().parents[2]),
            "--host",
            "panel.test",
            "--scheme",
            "http",
            flag,
            "0",
        ]
    )
    with pytest.raises(ValueError, match="port"):
        install(arguments)
    assert not (tmp_path / "install").exists()
