"""Prepared release binaries use real issued credentials and deliver a real service."""

import base64
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO
from uuid import uuid4

import pytest
from conftest import until
from django.http import FileResponse
from rest_framework.test import APIClient
from test_node_runtime import listening, port, stop
from test_nodes import node_input, owner_client
from xray_client import HttpTunnelProbe, subscription_client

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.runtime]
ROOT = Path(__file__).resolve().parents[3]


@dataclass
class PreparedNativeService:
    client: APIClient
    node_id: str
    service_url: str
    uri: str = field(repr=False)
    instance: Path
    probe: HttpTunnelProbe
    agent: subprocess.Popen
    command: tuple[str, ...]
    log: TextIO = field(repr=False)
    agent_port: int
    api_port: int

    def restart(self) -> None:
        stop(self.agent)
        until(lambda: not listening(self.api_port) and not listening(self.agent_port), timeout=5)
        self.agent = subprocess.Popen(self.command, stdout=self.log, stderr=subprocess.STDOUT)
        until(lambda: listening(self.agent_port) and listening(self.api_port), timeout=10)


@pytest.fixture
def prepared_native_service(runtime: None, tmp_path: Path) -> Iterator[PreparedNativeService]:
    bundle = os.environ.get("PAPILIO_NODE_BUNDLE")
    if not bundle:
        pytest.skip(
            "Provide the candidate prebuilt node bundle for native installation acceptance."
        )
    agent_port, api_port, data_port = port(), port(), port()
    client = owner_client("prepared-node-owner")
    made = client.post(
        "/api/v1/nodes",
        node_input()
        | {
            "endpoint_url": f"https://127.0.0.1:{agent_port}",
            "runtime": {
                "listen_address": f"127.0.0.1:{agent_port}",
                "xray_api_address": f"127.0.0.1:{api_port}",
                "request_timeout_seconds": 2,
            },
        },
        format="json",
    )
    assert made.status_code == 202
    node, work = made.json()["node"], made.json()["operation"]
    root = f"/api/v1/nodes/{node['id']}"
    until(lambda: client.get(root + f"/operations/{work['id']}").json()["status"] == "succeeded")
    response = client.post(root + "/bootstrap")
    assert isinstance(response, FileResponse) and response.status_code == 200
    stream = response.streaming_content
    assert isinstance(stream, Iterator)
    bootstrap = tmp_path / "bootstrap.zip"
    bootstrap.write_bytes(b"".join(stream))
    bootstrap.chmod(0o600)
    home = tmp_path / "native home"
    command = [
        sys.executable,
        str(ROOT / "deployment/papilio.py"),
        "--home",
        str(home),
        "--environment",
        "test",
        "node",
        "install",
        "--bootstrap",
        str(bootstrap),
        "--bundle",
        bundle,
        "--inbound-tag",
        "prepared-vless",
        "--listen",
        "127.0.0.1",
        "--port",
        str(data_port),
        "--prepare-only",
    ]
    prepared = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    assert prepared.returncode == 0, prepared.stderr
    instance = home / "nodes/test" / node["id"]
    configuration = instance / "credentials/agent.json"
    assert json.loads(configuration.read_text())["request_timeout_seconds"] == 2
    before = configuration.read_bytes()
    assert subprocess.run(command, capture_output=True, check=False, timeout=30).returncode == 0
    assert configuration.read_bytes() == before
    if shutil.which("systemd-analyze"):
        unit = instance / f"papilio-node-test-{node['id']}.service"
        verified = subprocess.run(
            ["systemd-analyze", "verify", str(unit)], capture_output=True, text=True, timeout=10
        )
        assert verified.returncode == 0, verified.stderr
    with (tmp_path / "managed-agent.log").open("w") as log:
        agent_command = (
            sys.executable,
            str(ROOT / "deployment/papilio.py"),
            "--home",
            str(home),
            "--environment",
            "test",
            "node",
            "run",
            "--node",
            node["id"],
        )
        agent = subprocess.Popen(agent_command, stdout=log, stderr=subprocess.STDOUT)
        live = None
        try:
            until(lambda: listening(agent_port) and listening(api_port), timeout=10)
            check = client.post(
                root + "/operations",
                {"kind": "check_connection", "request_key": str(uuid4())},
                format="json",
            )
            assert check.status_code == 202
            until(
                lambda: (
                    client.get(root + f"/operations/{check.json()['id']}").json()["status"]
                    in {"succeeded", "failed"}
                )
            )
            assert client.get(root).json()["last_reachable"] is True
            core = client.post(
                "/api/v1/cores/xray",
                {
                    "node_id": node["id"],
                    "request_key": str(uuid4()),
                    "name": "Prepared core",
                },
                format="json",
            )
            assert core.status_code == 201
            inbound = client.post(
                f"/api/v1/cores/{core.json()['id']}/xray/inbounds",
                {
                    "request_key": str(uuid4()),
                    "tag": "prepared-vless",
                    "public_host": "127.0.0.1",
                    "port": data_port,
                },
                format="json",
            )
            assert inbound.status_code == 201
            service = client.post(
                "/api/v1/services",
                {
                    "request_key": str(uuid4()),
                    "name": "Prepared native service",
                    "core_id": core.json()["id"],
                    "inbound_id": inbound.json()["id"],
                },
                format="json",
            )
            assert service.status_code == 202
            service_url = f"/api/v1/services/{service.json()['id']}"
            until(lambda: client.get(service_url).json()["status"] in {"succeeded", "failed"})
            assert client.get(service_url).json()["status"] == "succeeded"
            subscription = client.get(service_url + "/subscription")
            assert subscription.status_code == 200
            uri = base64.b64decode(client.get(subscription.json()["url"]).content).decode().strip()
            with subscription_client(str(instance / "bin/xray"), tmp_path, uri) as probe:
                assert probe.fetch() == b"papilio-actual-subscription-client"
                live = PreparedNativeService(
                    client,
                    node["id"],
                    service_url,
                    uri,
                    instance,
                    probe,
                    agent,
                    agent_command,
                    log,
                    agent_port,
                    api_port,
                )
                yield live
        finally:
            stop(live.agent if live is not None else agent)
    until(lambda: not listening(api_port) and not listening(agent_port), timeout=5)


def test_prebuilt_node_preparation_and_managed_core_deliver_a_native_subscription(
    prepared_native_service: PreparedNativeService,
) -> None:
    assert prepared_native_service.probe.fetch() == b"papilio-actual-subscription-client"
