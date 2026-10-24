"""First-owner setup through real Beat/workers/private files/Go/Xray/client traffic."""

import base64
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from conftest import until
from django.conf import settings
from django.db import connection
from django.test import override_settings
from django_celery_beat.models import PeriodicTask
from test_local_node_setup import initialize_local_owner, local_definition
from test_node_runtime import listening, port, stop
from xray_client import subscription_client

from papilio_panel.modules.nodes.models import Node, NodeCredentials

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.runtime]


@pytest.fixture
def local_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, request: pytest.FixtureRequest
) -> Iterator[Path]:
    root = tmp_path / "local-state"
    configuration = {
        "PAPILIO_LOCAL_NODE_AVAILABLE": "true",
        "PAPILIO_LOCAL_NODE_STATE_ROOT": str(root),
        "PAPILIO_LOCAL_XRAY_BINARY": os.environ["PAPILIO_XRAY_BINARY"],
    }
    for name, value in configuration.items():
        monkeypatch.setenv(name, value)
    with override_settings(
        PAPILIO_LOCAL_NODE_AVAILABLE=True,
        PAPILIO_LOCAL_NODE_STATE_ROOT=str(root),
        PAPILIO_LOCAL_XRAY_BINARY=os.environ["PAPILIO_XRAY_BINARY"],
    ):
        request.getfixturevalue("runtime")
        yield root


@pytest.mark.timeout(120)
def test_first_owner_prepares_native_runtime_and_delivers_a_working_subscription(
    local_runtime: Path,
    tmp_path: Path,
) -> None:
    key = f"{settings.PAPILIO_NAMESPACE}.local-node-outbox"
    schedule = PeriodicTask.objects.get(name=key)
    schedule.enabled = False
    schedule.save()
    agent_port, api_port, data_port = port(), port(), port()
    selected = local_definition() | {
        "node": {
            "name": "Local acceptance node",
            "endpoint_url": f"https://127.0.0.1:{agent_port}",
            "runtime": {
                "listen_address": f"127.0.0.1:{agent_port}",
                "xray_api_address": f"127.0.0.1:{api_port}",
                "request_timeout_seconds": 2,
            },
        },
        "public_host": "127.0.0.1",
        "public_port": data_port,
        "bind_address": "127.0.0.1",
        "bind_port": data_port,
    }
    with (tmp_path / "local-agent.log").open("w") as log:
        agent = subprocess.Popen(
            [
                os.environ["PAPILIO_AGENT_BINARY"],
                "-config",
                str(local_runtime / "instance/agent.json"),
                "-wait-for-config",
                "-config-check-interval",
                "100ms",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            client = initialize_local_owner(selected)
            root = "/api/v1/system/local-node"
            metadata = client.get(root).json()
            node_id = metadata["node_id"]
            until(lambda: NodeCredentials.objects.filter(node_id=node_id).exists())
            assert client.get(root).json()["operation"]["attempts"] == "0"
            assert not (local_runtime / "instance").exists() and not listening(agent_port)
            schedules = client.get("/api/v1/system/schedules").json()
            current = next(row for row in schedules if row["key"] == "local-node-outbox")
            response = client.put(
                "/api/v1/system/schedules/local-node-outbox",
                {
                    "enabled": True,
                    "interval_seconds": 1,
                    "expected_changed_at": current["changed_at"],
                },
                format="json",
            )
            assert response.status_code == 200
            until(lambda: client.get(root).json()["operation"]["status"] == "succeeded")
            outcome = client.get(root).json()
            assert outcome["operation"]["worker_pid"] != os.getpid()
            assert outcome["operation"]["attempts"] in {"1", "2", "3"}
            connection.close()
            assert Node.objects.get(pk=node_id).last_reachable is True
            assert listening(data_port) and agent.poll() is None
            before = {
                path.name: path.read_bytes() for path in (local_runtime / "instance").iterdir()
            }
            creation = client.post(
                "/api/v1/services",
                {
                    "request_key": str(uuid4()),
                    "name": "Automatically initialized local service",
                    "core_id": metadata["core_id"],
                    "inbound_id": metadata["inbound_id"],
                    "identifier": str(uuid4()),
                },
                format="json",
            )
            assert creation.status_code == 202
            service = f"/api/v1/services/{creation.json()['id']}"
            until(lambda: client.get(service).json()["status"] == "succeeded")
            link = client.get(service + "/subscription").json()["url"]
            uri = base64.b64decode(client.get(link).content).decode().strip()
            with subscription_client(os.environ["PAPILIO_XRAY_BINARY"], tmp_path, uri) as probe:
                assert probe.fetch() == b"papilio-actual-subscription-client"
            retry = client.post(root + "/operations", {"request_key": str(uuid4())}, format="json")
            assert retry.status_code == 202
            until(lambda: client.get(root).json()["operation"]["status"] == "succeeded")
            assert {
                path.name: path.read_bytes() for path in (local_runtime / "instance").iterdir()
            } == before
        finally:
            stop(agent)
