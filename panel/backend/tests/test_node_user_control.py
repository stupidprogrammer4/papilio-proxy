"""Scoped Django control through the real Go mTLS agent and native Xray."""

import io
import json
import os
import subprocess
import threading
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterator
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from conftest import until
from django.contrib.auth.models import User
from django.http import FileResponse
from test_node_runtime import listening, port, stop
from test_nodes import node_input, owner_client

from papilio_panel.modules.nodes.domain import (
    VlessUser,
    XrayApply,
    XrayRemove,
    XrayUserIdentity,
)
from papilio_panel.modules.nodes.providers import xray_control
from papilio_panel.shared.errors import AuthenticationRejected, InvalidInput, Missing

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.runtime]


@pytest.fixture
def native_control(runtime: None, tmp_path: Path) -> Iterator[tuple[XrayApply, int, str]]:
    core_binary = os.environ["PAPILIO_XRAY_BINARY"]
    agent_binary = os.environ["PAPILIO_AGENT_BINARY"]
    agent_port, core_port, data_port = port(), port(), port()
    client = owner_client("native-user-owner")
    made = client.post(
        "/api/v1/nodes",
        node_input()
        | {
            "endpoint_url": f"https://127.0.0.1:{agent_port}",
            "runtime": {
                "listen_address": f"127.0.0.1:{agent_port}",
                "xray_api_address": f"127.0.0.1:{core_port}",
                "request_timeout_seconds": 2,
            },
        },
        format="json",
    )
    assert made.status_code == 202
    node, work = made.json()["node"], made.json()["operation"]
    root = f"/api/v1/nodes/{node['id']}"
    until(lambda: client.get(root + f"/operations/{work['id']}").json()["status"] == "succeeded")
    archive_response = client.post(root + "/bootstrap")
    assert isinstance(archive_response, FileResponse)
    contents = archive_response.streaming_content
    assert isinstance(contents, Iterator)
    with zipfile.ZipFile(io.BytesIO(b"".join(contents))) as archive:
        for member in archive.infolist():
            path = tmp_path / member.filename
            path.write_bytes(archive.read(member))
            path.chmod(0o600)
    configuration = {
        "log": {"loglevel": "none"},
        "api": {
            "tag": "management",
            "listen": f"127.0.0.1:{core_port}",
            "services": ["HandlerService", "StatsService"],
        },
        "stats": {},
        "policy": {
            "levels": {
                "0": {"statsUserUplink": True, "statsUserDownlink": True},
            }
        },
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
    configuration_path = tmp_path / "xray.json"
    configuration_path.write_text(json.dumps(configuration))
    with (
        (tmp_path / "core.log").open("w") as core_log,
        (tmp_path / "agent.log").open("w") as agent_log,
    ):
        core = subprocess.Popen(
            [core_binary, "run", "-config", str(configuration_path)],
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
            yield (
                XrayApply(
                    actor_id=node["owner_id"],
                    node_id=UUID(node["id"]),
                    user=VlessUser(
                        identity=XrayUserIdentity("vless-test", "native-user"), identifier=uuid4()
                    ),
                ),
                data_port,
                core_binary,
            )
        finally:
            if agent is not None:
                stop(agent)
            stop(core)


def test_native_apply_replay_and_remove_change_actual_client_access(
    native_control: tuple[XrayApply, int, str], tmp_path: Path
) -> None:
    values, data_port, binary = native_control
    proxy_port = port()
    config = {
        "log": {"loglevel": "none"},
        "inbounds": [{"protocol": "http", "listen": "127.0.0.1", "port": proxy_port}],
        "outbounds": [
            {
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": "127.0.0.1",
                            "port": data_port,
                            "users": [{"id": str(values.user.identifier), "encryption": "none"}],
                        }
                    ]
                },
            }
        ],
    }
    path = tmp_path / "client.json"
    path.write_text(json.dumps(config))

    class Origin(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            payload = b"papilio-real-client-traffic"
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            pass

    origin = ThreadingHTTPServer(("127.0.0.1", 0), Origin)
    thread = threading.Thread(target=origin.serve_forever, daemon=True)
    thread.start()
    with (tmp_path / "client.log").open("w") as log:
        proxy = subprocess.Popen(
            [binary, "run", "-config", str(path)], stdout=log, stderr=subprocess.STDOUT
        )
        try:
            until(lambda: listening(proxy_port), timeout=10)

            # An explicit proxy prevents urllib's localhost bypass from hiding a failed tunnel.
            def fetch() -> bytes:
                request = urllib.request.Request(f"http://127.0.0.1:{origin.server_port}/")
                request.set_proxy(f"127.0.0.1:{proxy_port}", "http")
                with urllib.request.urlopen(request, timeout=3) as response:
                    return response.read()

            with pytest.raises((OSError, urllib.error.URLError)):
                fetch()
            first = xray_control.apply(values)
            assert first.succeeded and first.changed is True, first
            assert xray_control.apply(values).changed is False
            assert fetch() == b"papilio-real-client-traffic"
            escaped = replace(
                values,
                user=replace(
                    values.user,
                    identifier=uuid4(),
                    identity=XrayUserIdentity("vless-test", "user+literal/../name?tag=wrong#piece"),
                ),
            )
            assert xray_control.apply(escaped).changed is True
            assert (
                xray_control.remove(
                    XrayRemove(escaped.actor_id, escaped.node_id, escaped.user.identity)
                ).changed
                is True
            )
            owner_client("stranger")
            stranger_id = User.objects.get(username="stranger").pk
            with pytest.raises(Missing):
                xray_control.apply(replace(values, actor_id=stranger_id))
            removal = XrayRemove(values.actor_id, values.node_id, values.user.identity)
            with pytest.raises(Missing):
                xray_control.remove(replace(removal, actor_id=stranger_id))
            User.objects.filter(pk=values.actor_id).update(is_active=False)
            with pytest.raises(AuthenticationRejected):
                xray_control.remove(removal)
            User.objects.filter(pk=values.actor_id).update(is_active=True)
            assert fetch() == b"papilio-real-client-traffic"
            assert xray_control.remove(removal).changed is True
            assert xray_control.remove(removal).changed is False
            with pytest.raises((OSError, urllib.error.URLError)):
                fetch()
        finally:
            stop(proxy)
            origin.shutdown()
            origin.server_close()
            thread.join(timeout=3)


@pytest.mark.parametrize(
    "identity",
    [
        XrayUserIdentity("", "user"),
        XrayUserIdentity("inbound", "UPPER"),
        XrayUserIdentity("inbound", "a>>>uplink"),
        XrayUserIdentity(" tag", "user"),
    ],
)
def test_invalid_native_identity_is_rejected_before_external_access(
    identity: XrayUserIdentity,
) -> None:
    actor = User.objects.create_superuser(username="validation-owner")
    values = XrayRemove(actor.pk, uuid4(), identity)
    with pytest.raises(InvalidInput):
        xray_control.remove(values)


def test_inactive_actor_cannot_control_a_node() -> None:
    actor = User.objects.create_superuser(username="inactive-owner", is_active=False)
    values = XrayRemove(actor.pk, uuid4(), XrayUserIdentity("inbound", "user"))
    with pytest.raises(AuthenticationRejected):
        xray_control.remove(values)
