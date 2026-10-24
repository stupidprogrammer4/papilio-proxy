"""Native preparation preserves operator files and refuses conflicting identity."""

import json
import os
import shutil
import subprocess
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
from deployment.papilio_installer.node.artifacts import BundleFile, inspect_bundle, native_platform
from deployment.papilio_installer.node.configuration import NodeInstallSettings, inspect_bootstrap
from deployment.papilio_installer.node.installation import prepare_installation
from deployment.papilio_installer.node.packaging import write_bundle
from test_node_configuration import bootstrap


@pytest.fixture(scope="module")
def native_bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    agent = os.environ.get("PAPILIO_AGENT_BINARY")
    xray = os.environ.get("PAPILIO_XRAY_BINARY")
    if not agent or not xray:
        pytest.skip("Build the actual node agent and provide the verified Xray binary.")
    source = Path(__file__).resolve().parents[2]
    tmp_path = tmp_path_factory.mktemp("native-node-bundle")
    return write_bundle(
        tmp_path / "native.tar.gz",
        "0.1.0-alpha.4",
        native_platform(),
        Path(agent),
        Path(xray),
        source / "LICENSE",
        source / "LICENSE",
        source / "LICENSE",
    )


def private_bootstrap(path: Path) -> Path:
    source = bootstrap(path)
    with zipfile.ZipFile(source) as archive:
        configuration = archive.read("agent.json")
    key = path.parent / "issued.key"
    certificate = path.parent / "issued.crt"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(key),
            "-out",
            str(certificate),
            "-subj",
            "/CN=localhost",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("agent.json", configuration)
        archive.writestr("server.key", key.read_bytes())
        archive.writestr("server.crt", certificate.read_bytes())
        archive.writestr("client-ca.crt", certificate.read_bytes())
    return source


def test_preparation_validates_real_core_and_preserves_modified_settings_on_reinstall(
    tmp_path: Path, native_bundle: Path
) -> None:
    issued = inspect_bootstrap(private_bootstrap(tmp_path / "bootstrap.zip"))
    bundle = inspect_bundle(native_bundle, native_platform())
    settings = NodeInstallSettings(environment="test", port=28443)
    root = tmp_path / "installed" / "test" / str(issued.node_id)
    prepared = prepare_installation(root, bundle, issued, settings)
    assert prepared.root == root and prepared.node_id == issued.node_id
    assert (root / "credentials").stat().st_mode & 0o777 == 0o700
    for path in (root / "credentials").iterdir():
        assert path.stat().st_mode & 0o777 == 0o600
    assert (root / "credentials/server.key").read_bytes() == issued.files["server.key"]
    configuration = root / "credentials/xray.json"
    value = json.loads(configuration.read_text())
    value["log"]["loglevel"] = "none"
    configuration.write_text(json.dumps(value))
    original = configuration.read_bytes()
    assert prepare_installation(root, bundle, issued, settings) == prepared
    assert configuration.read_bytes() == original
    assert not list(root.parent.glob(".node-stage-*"))


def test_conflicts_cannot_replace_an_existing_node_or_unrelated_directory(
    tmp_path: Path, native_bundle: Path
) -> None:
    issued = inspect_bootstrap(private_bootstrap(tmp_path / "bootstrap.zip"))
    bundle = inspect_bundle(native_bundle, native_platform())
    root = tmp_path / "node"
    root.mkdir()
    marker = root / "operator-file"
    marker.write_text("keep")
    with pytest.raises(ValueError):
        prepare_installation(root, bundle, issued, NodeInstallSettings())
    assert marker.read_text() == "keep"
    shutil.rmtree(root)
    prepare_installation(root, bundle, issued, NodeInstallSettings())
    original = (root / "credentials/agent.json").read_bytes()
    with pytest.raises(ValueError):
        prepare_installation(root, bundle, issued, NodeInstallSettings(port=28444))
    altered = replace(bundle, files=bundle.files | {"bin/xray": BundleFile("0" * 64, 64)})
    with pytest.raises(ValueError):
        prepare_installation(root, altered, issued, NodeInstallSettings())
    assert (root / "credentials/agent.json").read_bytes() == original


def test_invalid_credentials_leave_no_prepared_installation(
    tmp_path: Path, native_bundle: Path
) -> None:
    issued = inspect_bootstrap(bootstrap(tmp_path / "bootstrap.zip"))
    root = tmp_path / "node"
    with pytest.raises(ValueError):
        prepare_installation(
            root, inspect_bundle(native_bundle, native_platform()), issued, NodeInstallSettings()
        )
    assert not root.exists() and not list(tmp_path.glob(".node-stage-*"))


def test_private_umask_keeps_native_binaries_accessible_and_credentials_private(
    tmp_path: Path, native_bundle: Path
) -> None:
    issued = inspect_bootstrap(private_bootstrap(tmp_path / "bootstrap.zip"))
    home = tmp_path / "native-home"
    root = home / "test" / str(issued.node_id)
    previous = os.umask(0o077)
    try:
        prepare_installation(
            root,
            inspect_bundle(native_bundle, native_platform()),
            issued,
            NodeInstallSettings(environment="test"),
        )
    finally:
        os.umask(previous)
    for folder in (home, root.parent, root, root / "bin"):
        assert folder.stat().st_mode & 0o777 == 0o755
    assert (root / "credentials").stat().st_mode & 0o777 == 0o700
    assert (root / "credentials/server.key").stat().st_mode & 0o777 == 0o600
    assert tmp_path.stat().st_mode & 0o777 == 0o700
