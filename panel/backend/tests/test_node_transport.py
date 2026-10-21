"""Native mTLS transport against a controlled external HTTPS agent double."""

import json
import ssl
import threading
from collections.abc import Iterator
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import pytest

from papilio_panel.modules.nodes.domain import (
    AgentRuntime,
    CertificateInput,
    CertificatePolicy,
    NodeConnection,
)
from papilio_panel.modules.nodes.infra.agent import NativeAgentGateway, write_private
from papilio_panel.modules.nodes.infra.certificates import NativeCertificateIssuer


@pytest.fixture
def agent_endpoint(tmp_path: Path) -> Iterator[tuple[NodeConnection, list[object]]]:
    node_id, deployment_id = uuid4(), uuid4()
    credentials = NativeCertificateIssuer().issue(
        CertificateInput(
            node_id=node_id,
            deployment_id=deployment_id,
            hostname="127.0.0.1",
            policy=CertificatePolicy(),
        )
    )
    responses: list[object] = [
        {"node_id": str(node_id), "protocol_version": 1, "core": {"uptime_seconds": 8}}
    ]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = json.dumps(responses[0]).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    certificate, key = tmp_path / "server.crt", tmp_path / "server.key"
    write_private(certificate, credentials.server_certificate)
    write_private(key, credentials.private_keys.server)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_verify_locations(cadata=credentials.authority_certificate)
    context.load_cert_chain(str(certificate), str(key))
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield (
            NodeConnection(
                node_id=node_id,
                deployment_id=deployment_id,
                endpoint_url=f"https://127.0.0.1:{server.server_port}",
                runtime=AgentRuntime(request_timeout_seconds=1),
                credentials=credentials,
            ),
            responses,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"node_id": 9, "protocol_version": 1},
        {"node_id": "replace", "protocol_version": True, "core": {"uptime_seconds": 8}},
        {"node_id": "replace", "protocol_version": 1, "core": []},
        {"node_id": "replace", "protocol_version": 1, "core": {"uptime_seconds": True}},
    ],
)
def test_malformed_external_agent_payload_fails_safely(
    agent_endpoint: tuple[NodeConnection, list[object]], payload: object
) -> None:
    connection, responses = agent_endpoint
    if isinstance(payload, dict) and payload.get("node_id") == "replace":
        payload = payload | {"node_id": str(connection.node_id)}
    responses[0] = payload
    result = NativeAgentGateway().check(connection)
    assert result.reachable is False
    assert result.error_code == "invalid_node_response"


def test_native_mtls_requires_expected_node_identity_and_issued_authority(
    agent_endpoint: tuple[NodeConnection, list[object]],
) -> None:
    connection, _ = agent_endpoint
    assert NativeAgentGateway().check(connection).uptime_seconds == 8
    mismatched = NativeAgentGateway().check(replace(connection, node_id=uuid4()))
    assert mismatched.reachable is False
    assert mismatched.error_code == "node_identity_mismatch"
    other = NativeCertificateIssuer().issue(
        CertificateInput(
            node_id=uuid4(), deployment_id=uuid4(), hostname="127.0.0.1", policy=CertificatePolicy()
        )
    )
    rejected = NativeAgentGateway().check(replace(connection, credentials=other))
    assert rejected.reachable is False
    assert rejected.error_code == "tls_rejected"
