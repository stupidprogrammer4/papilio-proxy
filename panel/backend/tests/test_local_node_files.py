"""Native private instance publication preserves operator files and rejects root escapes."""

import io
import json
import zipfile
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from papilio_panel.modules.local_nodes.domain import LocalDefinition
from papilio_panel.modules.nodes.domain import (
    AgentRuntime,
    CertificatePolicy,
    NodeDefinition,
    NodeRead,
)
from papilio_panel.shared.errors import ApplicationError


def private_local_bootstrap():
    from papilio_panel.modules.local_nodes.domain import LocalBootstrap

    node_id, deployment_id = uuid4(), uuid4()
    runtime = AgentRuntime()
    node = NodeRead(
        node_id,
        deployment_id,
        1,
        "Local node",
        "https://local-node.papilio.internal:9443",
        runtime,
        CertificatePolicy(),
        True,
        None,
        None,
        None,
        None,
        None,
        None,
    )
    definition = LocalDefinition(
        NodeDefinition(node.name, node.endpoint_url, runtime),
        "Local Xray",
        "vless",
        "vpn.example.test",
        8444,
    )
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr(
            "agent.json",
            json.dumps(
                {
                    "node_id": str(node_id),
                    "deployment_id": str(deployment_id),
                    "tls_certificate_file": "server.crt",
                    "tls_key_file": "server.key",
                    "client_ca_file": "client-ca.crt",
                }
            ),
        )
        for name in ("server.crt", "server.key", "client-ca.crt"):
            archive.writestr(name, b"private-test-input-not-a-real-credential")
    return LocalBootstrap(uuid4(), node, definition, content.getvalue())


def test_publication_creates_one_complete_private_instance_and_preserves_operator_changes(
    tmp_path: Path,
) -> None:
    from papilio_panel.modules.local_nodes.infra.files import NativeLocalFiles

    supplied = private_local_bootstrap()
    root = tmp_path / "local-state"
    publisher = NativeLocalFiles(root)
    publisher.publish(supplied)
    target = root / "instance"
    assert target.stat().st_mode & 0o777 == 0o700
    assert {path.name for path in target.iterdir()} == {
        "agent.json",
        "xray.json",
        "server.crt",
        "server.key",
        "client-ca.crt",
        "papilio.json",
    }
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in target.iterdir())
    configuration = json.loads((target / "agent.json").read_text())
    assert configuration["managed_xray"] == {
        "binary_file": "/usr/local/bin/xray",
        "configuration_file": "xray.json",
    }
    configuration["idle_timeout_seconds"] = 71
    (target / "agent.json").write_text(json.dumps(configuration))
    before = {path.name: path.read_bytes() for path in target.iterdir()}
    publisher.publish(replace(supplied, operation_id=uuid4()))
    assert {path.name: path.read_bytes() for path in target.iterdir()} == before
    assert sorted(path.name for path in root.iterdir()) == ["instance"]


@pytest.mark.parametrize(
    "case", ["wrong_identity", "target_symlink", "file_symlink", "unrelated_directory"]
)
def test_publication_never_replaces_foreign_or_escaped_operator_resources(
    tmp_path: Path, case: str
) -> None:
    from papilio_panel.modules.local_nodes.infra.files import NativeLocalFiles

    supplied = private_local_bootstrap()
    root, outside = tmp_path / "local-state", tmp_path / "operator"
    outside.mkdir()
    marker = outside / "keep"
    marker.write_bytes(b"unrelated-operator-content")
    root.mkdir()
    publisher = NativeLocalFiles(root)
    if case == "target_symlink":
        (root / "instance").symlink_to(outside, target_is_directory=True)
    elif case == "unrelated_directory":
        (root / "instance").mkdir()
        (root / "instance/keep").write_bytes(b"retain")
    else:
        publisher.publish(supplied)
        if case == "wrong_identity":
            supplied = replace(supplied, node=replace(supplied.node, id=uuid4()))
        else:
            key = root / "instance/server.key"
            key.unlink()
            key.symlink_to(marker)
    with pytest.raises(ApplicationError):
        publisher.publish(supplied)
    assert marker.read_bytes() == b"unrelated-operator-content"
    if case == "unrelated_directory":
        assert (root / "instance/keep").read_bytes() == b"retain"


def test_invalid_bootstrap_cannot_publish_a_partial_instance(tmp_path: Path) -> None:
    from papilio_panel.modules.local_nodes.infra.files import NativeLocalFiles

    supplied = private_local_bootstrap()
    root = tmp_path / "local-state"
    with pytest.raises(ApplicationError):
        NativeLocalFiles(root).publish(replace(supplied, archive=b"not-a-zip"))
    assert not (root / "instance").exists()
