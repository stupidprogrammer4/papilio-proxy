"""Actual API, PostgreSQL, Beat, workers, mTLS Go agent and native Xray boundary."""

import io
import json
import os
import socket
import subprocess
import zipfile
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from celery.canvas import Signature
from conftest import until
from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID
from django.http import FileResponse
from test_nodes import node_input, owner_client

from papilio_panel.modules.nodes.domain import NodeTaskName
from papilio_panel.modules.nodes.models import NodeCredentials

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.runtime]


def port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        result = listener.getsockname()[1]
    return result


def listening(number: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", number), timeout=0.1):
            return True
    except OSError:
        return False


def stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def test_real_workers_issue_private_bootstrap_and_connect_to_go_agent(
    runtime: None, tmp_path: Path
) -> None:
    agent_binary = os.environ.get("PAPILIO_AGENT_BINARY")
    xray_binary = os.environ.get("PAPILIO_XRAY_BINARY")
    if not agent_binary or not xray_binary:
        pytest.skip(
            "Verified Xray and built Papilio agent binaries are required for this boundary."
        )
    agent_port, core_port, data_port = port(), port(), port()
    values = node_input() | {
        "endpoint_url": f"https://127.0.0.1:{agent_port}",
        "runtime": {
            "listen_address": f"127.0.0.1:{agent_port}",
            "xray_api_address": f"127.0.0.1:{core_port}",
            "request_timeout_seconds": 2,
        },
    }
    client = owner_client()
    created = client.post("/api/v1/nodes", values, format="json")
    assert created.status_code == 202
    node, operation = created.json()["node"], created.json()["operation"]
    root = f"/api/v1/nodes/{node['id']}"
    operation_url = f"{root}/operations/{operation['id']}"
    until(lambda: client.get(operation_url).json()["status"] == "succeeded")
    issued = client.get(operation_url).json()
    assert issued["worker_pid"] != os.getpid()
    assert issued["attempts"] == 1
    stored = NodeCredentials.objects.get(node_id=UUID(node["id"]))
    ciphertext = bytes(stored.secrets_ciphertext)
    assert b"PRIVATE KEY" not in ciphertext
    bootstrap = client.post(root + "/bootstrap")
    assert isinstance(bootstrap, FileResponse)
    assert bootstrap.status_code == 200
    assert bootstrap["Cache-Control"] == "private, no-store"
    stream = bootstrap.streaming_content
    assert isinstance(stream, Iterator)
    with zipfile.ZipFile(io.BytesIO(b"".join(stream))) as archive:
        assert set(archive.namelist()) == {
            "agent.json",
            "server.key",
            "server.crt",
            "client-ca.crt",
        }
        for entry in archive.infolist():
            assert (entry.external_attr >> 16) & 0o777 == 0o600
            path = tmp_path / entry.filename
            path.write_bytes(archive.read(entry))
            path.chmod(0o600)
    server = x509.load_pem_x509_certificate((tmp_path / "server.crt").read_bytes())
    assert list(server.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value) == [
        ExtendedKeyUsageOID.SERVER_AUTH
    ]
    names = server.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert names.get_values_for_type(x509.UniformResourceIdentifier) == [
        f"spiffe://papilio/{node['deployment_id']}/nodes/{node['id']}/agent"
    ]
    Signature(NodeTaskName.ISSUE.value, kwargs={"operation_id": operation["id"]}).apply_async()
    sentinel = client.post("/api/v1/nodes", node_input("sentinel"), format="json").json()
    until(
        lambda: (
            client.get(
                f"/api/v1/nodes/{sentinel['node']['id']}/operations/{sentinel['operation']['id']}"
            ).json()["status"]
            == "succeeded"
        )
    )
    assert client.get(operation_url).json()["attempts"] == 1
    assert (
        bytes(NodeCredentials.objects.get(node_id=UUID(node["id"])).secrets_ciphertext)
        == ciphertext
    )
    configuration = {
        "log": {"loglevel": "none"},
        "api": {
            "tag": "management",
            "listen": f"127.0.0.1:{core_port}",
            "services": ["HandlerService", "StatsService"],
        },
        "stats": {},
        "inbounds": [
            {
                "tag": "vless-test",
                "listen": "127.0.0.1",
                "port": data_port,
                "protocol": "vless",
                "settings": {"clients": [], "decryption": "none"},
            }
        ],
        "outbounds": [{"protocol": "freedom", "tag": "direct"}],
    }
    core_config = tmp_path / "xray.json"
    core_config.write_text(json.dumps(configuration))
    with (
        (tmp_path / "xray.log").open("w") as core_log,
        (tmp_path / "agent.log").open("w") as agent_log,
    ):
        core = subprocess.Popen(
            [xray_binary, "run", "-config", str(core_config)],
            stdout=core_log,
            stderr=subprocess.STDOUT,
        )
        agent = None
        try:
            until(lambda: listening(core_port), timeout=10)
            agent = subprocess.Popen(
                [agent_binary, "-config", str(tmp_path / "agent.json")],
                stdout=agent_log,
                stderr=subprocess.STDOUT,
            )
            until(lambda: listening(agent_port), timeout=10)
            submitted = client.post(
                root + "/operations",
                {"kind": "check_connection", "request_key": str(uuid4())},
                format="json",
            )
            assert submitted.status_code == 202
            check_url = f"{root}/operations/{submitted.json()['id']}"
            until(lambda: client.get(check_url).json()["status"] in {"succeeded", "failed"})
            checked = client.get(check_url).json()
            assert checked["status"] == "succeeded", checked
            assert checked["worker_pid"] not in {os.getpid(), issued["worker_pid"]}
            observed = client.get(root).json()
            assert observed["last_reachable"] is True
            assert observed["last_error_code"] is None
            assert observed["uptime_seconds"] >= 0
            stop(agent)
            agent = None
            failed = client.post(
                root + "/operations",
                {"kind": "check_connection", "request_key": str(uuid4())},
                format="json",
            ).json()
            failed_url = f"{root}/operations/{failed['id']}"
            until(lambda: client.get(failed_url).json()["status"] == "failed")
            assert client.get(failed_url).json()["error_code"] == "connection_failed"
            assert client.get(root).json()["last_reachable"] is False
        finally:
            if agent is not None:
                stop(agent)
            stop(core)
