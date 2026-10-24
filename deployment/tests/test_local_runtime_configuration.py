"""New local-runtime defaults and legacy settings preserve explicit operator choices."""

import json
import socket
from pathlib import Path

import pytest
from deployment.papilio_installer.cli import parser, selected_settings
from deployment.papilio_installer.configuration import Installation, InstallSettings
from deployment.papilio_installer.docker import Compose
from deployment.papilio_installer.preflight import check_ports
from deployment.papilio_installer.tui import ConfigurationForm


def test_new_cli_install_enables_local_runtime_with_explicit_opt_out(tmp_path: Path) -> None:
    arguments = parser().parse_args(
        ["--home", str(tmp_path), "install", "--host", "vpn.example.test"]
    )
    settings = selected_settings(arguments)
    assert settings.local_node is True and settings.node_port == 8444
    arguments = parser().parse_args(
        ["--home", str(tmp_path), "install", "--no-local-node", "--node-port", "18444"]
    )
    selected = selected_settings(arguments)
    assert selected.local_node is False and selected.node_port == 18444


def test_resume_validates_the_saved_opt_out_before_applying_new_port_defaults(
    tmp_path: Path,
) -> None:
    previous = Installation.create(
        tmp_path,
        Path.cwd(),
        InstallSettings(
            host="localhost",
            http_port=8444,
            local_node=False,
        ),
    )
    before = (previous.root / "runtime.env").read_bytes()
    arguments = parser().parse_args(
        [
            "--home",
            str(tmp_path),
            "install",
            "--host",
            "localhost",
            "--port",
            "8444",
        ]
    )
    selected = selected_settings(arguments)
    assert selected.local_node is False and selected.http_port == 8444
    assert (previous.root / "runtime.env").read_bytes() == before


def test_persisted_local_runtime_and_tui_keep_the_installed_mapping(tmp_path: Path) -> None:
    settings = InstallSettings.from_options(
        environment="sandbox", host="vpn.example.test", node_port=18444
    )
    installation = Installation.create(tmp_path, Path.cwd(), settings)
    assert installation.values["PAPILIO_LOCAL_NODE_AVAILABLE"] == "true"
    assert installation.values["PAPILIO_LOCAL_NODE_PUBLIC_HOST"] == "vpn.example.test"
    assert installation.values["PAPILIO_LOCAL_NODE_PUBLIC_PORT"] == "18444"
    assert installation.values["PAPILIO_NODE_PORT"] == "18444"
    assert Installation.load(installation.root).settings == settings
    form = ConfigurationForm.from_settings(settings)
    assert form.settings().matches(settings)
    form.local_node.value = "off"
    assert form.settings().local_node is False
    assert form.settings().node_port == 18444


def test_legacy_installation_never_implicitly_enables_a_new_runtime(tmp_path: Path) -> None:
    installation = Installation.create(tmp_path, Path.cwd(), InstallSettings())
    path = installation.root / "installation.json"
    metadata = json.loads(path.read_text())
    metadata["settings"].pop("local_node", None)
    metadata["settings"].pop("node_port", None)
    path.write_text(json.dumps(metadata))
    before = (installation.root / "runtime.env").read_bytes()
    reloaded = Installation.load(installation.root)
    assert reloaded.settings.local_node is False
    assert (installation.root / "runtime.env").read_bytes() == before


def test_local_port_conflicts_are_rejected_before_any_installation_change(tmp_path: Path) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with socket.socket() as available:
            available.bind(("127.0.0.1", 0))
            web_port = available.getsockname()[1]
        with pytest.raises(ValueError, match="port"):
            check_ports(
                InstallSettings.from_options(
                    environment="sandbox", http_port=web_port, node_port=listener.getsockname()[1]
                )
            )
    assert not list(tmp_path.iterdir())


def test_legacy_source_cannot_silently_build_an_unavailable_local_runtime(tmp_path: Path) -> None:
    source = tmp_path / "older-release"
    source.mkdir()
    state = tmp_path / "installation"
    selected = InstallSettings.from_options(environment="sandbox")
    with pytest.raises(ValueError, match="no bundled local runtime"):
        Compose(Installation(state, source, selected, {}))
    assert not state.exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"node_port": 0},
        {"node_port": 65536},
        {"node_port": True},
        {"local_node": "true"},
        {"local_node": True, "node_port": 8080},
        {"local_node": True, "node_port": 8443, "scheme": "https"},
    ],
)
def test_invalid_local_settings_never_create_installation_files(
    tmp_path: Path, changes: dict
) -> None:
    with pytest.raises(ValueError):
        Installation.create(tmp_path, Path.cwd(), InstallSettings(**changes))
    assert not list(tmp_path.iterdir())
