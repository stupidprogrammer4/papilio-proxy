"""Native node seeds, instance identity and private input archive boundaries."""

import io
import json
import zipfile
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from deployment.papilio_installer.node.configuration import (
    NodeInstallSettings,
    inspect_bootstrap,
    seed_xray,
    service_unit,
)


def bootstrap(path: Path, extra: str | None = None) -> Path:
    values = {
        "node_id": str(uuid4()),
        "deployment_id": str(uuid4()),
        "listen_address": "127.0.0.1:9443",
        "xray_api_address": "127.0.0.1:10085",
        "shutdown_timeout_seconds": 20,
        "tls_certificate_file": "server.crt",
        "tls_key_file": "server.key",
        "client_ca_file": "client-ca.crt",
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("agent.json", json.dumps(values))
        for name in ("server.crt", "server.key", "client-ca.crt"):
            archive.writestr(name, "private fixture input")
        if extra:
            archive.writestr(extra, "must not extract")
    return path


def test_seed_exposes_only_loopback_core_api_and_explicit_inbound(tmp_path: Path) -> None:
    supplied = inspect_bootstrap(bootstrap(tmp_path / "bootstrap.zip"))
    settings = NodeInstallSettings(inbound_tag="edge-vless", listen_address="0.0.0.0", port=8443)
    value = seed_xray(supplied, settings)
    assert value["api"]["listen"] == "127.0.0.1:10085"
    assert value["api"]["services"] == ["HandlerService", "StatsService"]
    assert value["inbounds"] == [
        {
            "tag": "edge-vless",
            "listen": "0.0.0.0",
            "port": 8443,
            "protocol": "vless",
            "settings": {"clients": [], "decryption": "none"},
        }
    ]


@pytest.mark.parametrize("extra", ["../escape", "/etc/passwd", "control.key", "nested/file"])
def test_bootstrap_rejects_unexpected_members_without_extraction(
    tmp_path: Path, extra: str
) -> None:
    source = bootstrap(tmp_path / "bootstrap.zip", extra)
    with pytest.raises(ValueError):
        inspect_bootstrap(source)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bootstrap.zip"]


def test_bootstrap_rejects_duplicate_and_oversized_members(tmp_path: Path) -> None:
    source = bootstrap(tmp_path / "bootstrap.zip")
    with zipfile.ZipFile(source, "a") as archive, pytest.warns(UserWarning):
        archive.writestr("server.key", "replacement")
    with pytest.raises(ValueError):
        inspect_bootstrap(source)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("agent.json", "x" * 1048577)
    source.write_bytes(buffer.getvalue())
    with pytest.raises(ValueError):
        inspect_bootstrap(source)


@pytest.mark.parametrize(
    "settings",
    [
        NodeInstallSettings(port=0),
        NodeInstallSettings(port=65536),
        NodeInstallSettings(port=True),
        NodeInstallSettings(inbound_tag="management"),
        NodeInstallSettings(inbound_tag="bad\nunit"),
        NodeInstallSettings(inbound_tag=" vless "),
        NodeInstallSettings(listen_address="public.example.com"),
        NodeInstallSettings(environment="../../production"),
        NodeInstallSettings(restart_seconds=0),
    ],
)
def test_invalid_options_cannot_generate_runtime_configuration(
    settings: NodeInstallSettings,
) -> None:
    with pytest.raises(ValueError):
        settings.validate()


def test_service_uses_native_private_credentials_and_bounded_shutdown(tmp_path: Path) -> None:
    supplied = inspect_bootstrap(bootstrap(tmp_path / "bootstrap.zip"))
    settings = NodeInstallSettings(environment="sandbox", restart_seconds=7)
    unit = service_unit(tmp_path / "node instance", supplied, settings)
    assert "DynamicUser=yes" in unit
    assert "LoadCredential=server.key:" in unit
    assert "-config %d/agent.json" in unit
    assert "Restart=on-failure" in unit and "RestartSec=7s" in unit
    assert "TimeoutStopSec=65s" in unit
    assert "CAP_NET_BIND_SERVICE" in unit
    assert "PrivateKey=" not in unit and "private fixture input" not in unit
    with pytest.raises(ValueError):
        service_unit(tmp_path / "bad\npath", supplied, settings)
    with pytest.raises(ValueError):
        seed_xray(
            replace(supplied, runtime=supplied.runtime | {"xray_api_address": "0.0.0.0:10085"}),
            settings,
        )


@pytest.mark.parametrize(
    "name", ["node instance", "node % instance", 'node "instance"', r"node \ instance"]
)
def test_credential_sources_preserve_literal_paths_without_shell_quoting(
    tmp_path: Path,
    name: str,
) -> None:
    supplied = inspect_bootstrap(bootstrap(tmp_path / "bootstrap.zip"))
    root = tmp_path / name
    unit = service_unit(root, supplied, NodeInstallSettings())
    expected = f"server.key:{str(root).replace('%', '%%')}/credentials/server.key"
    assert f"LoadCredential={expected}" in unit.splitlines()
