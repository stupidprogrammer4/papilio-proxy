"""Native mTLS transport against a controlled external HTTPS agent double."""

import json
import ssl
import threading
from collections.abc import Iterator
from contextlib import suppress
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
    VlessUser,
    XrayUserIdentity,
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
        {"node_id": str(node_id), "protocol_version": 1, "core": {"uptime_seconds": 8}},
        200,
    ]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = json.dumps(responses[0]).encode()
            status = responses[1]
            assert isinstance(status, int)
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            # Limit/identity rejection may close before the controlled double replies.
            with suppress(BrokenPipeError, ConnectionResetError, ssl.SSLEOFError):
                self.wfile.write(body)

        def do_PUT(self) -> None:
            self.rfile.read(int(self.headers["Content-Length"]))
            self.do_GET()

        do_DELETE = do_GET

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


@pytest.mark.parametrize("method", ["apply", "remove"])
@pytest.mark.parametrize(
    "payload", [None, [], {}, {"changed": "yes"}, {"changed": 1}, {"changed": None}]
)
def test_invalid_mutation_replies_do_not_claim_success(
    agent_endpoint: tuple[NodeConnection, list[object]], method: str, payload: object
) -> None:
    connection, responses = agent_endpoint
    responses[0] = (
        payload | {"node_id": str(connection.node_id)} if isinstance(payload, dict) else payload
    )
    identity = XrayUserIdentity("inbound", "native-user")
    gateway = NativeAgentGateway()
    if method == "apply":
        result = gateway.apply_vless(connection, VlessUser(identity, uuid4()))
    else:
        result = gateway.remove_xray(connection, identity)
    assert result.succeeded is False
    assert result.changed is None
    assert result.error_code == "invalid_node_response"


@pytest.mark.parametrize(
    "status,code",
    [
        (400, "invalid_input"),
        (409, "unsupported_account"),
        (408, "request_cancelled"),
        (502, "core_rejected"),
        (504, "core_timeout"),
        (503, "core_unavailable"),
        (503, "core_resource_limit"),
    ],
)
def test_recognized_agent_errors_remain_typed_technical_failures(
    agent_endpoint: tuple[NodeConnection, list[object]], status: int, code: str
) -> None:
    connection, responses = agent_endpoint
    responses[:] = [{"code": code}, status]
    result = NativeAgentGateway().remove_xray(connection, XrayUserIdentity("inbound", "user"))
    assert result.succeeded is False
    assert result.changed is None
    assert result.error_code == code


def test_mutations_reject_wrong_node_unknown_errors_and_oversized_responses(
    agent_endpoint: tuple[NodeConnection, list[object]],
) -> None:
    connection, responses = agent_endpoint
    identity = XrayUserIdentity("inbound", "user")
    gateway = NativeAgentGateway()
    responses[0] = {"node_id": str(uuid4()), "changed": True}
    assert gateway.remove_xray(connection, identity).error_code == "node_identity_mismatch"
    responses[:] = [{"code": "arbitrary-private-server-error"}, 503]
    assert gateway.remove_xray(connection, identity).error_code == "invalid_node_response"
    responses[:] = [{"node_id": str(connection.node_id), "changed": True}, 200]
    bounded = replace(connection, runtime=replace(connection.runtime, max_grpc_reply_bytes=8))
    assert gateway.remove_xray(bounded, identity).error_code == "node_response_limit"
    assert (
        gateway.apply_vless(
            replace(connection, node_id=uuid4()), VlessUser(identity, uuid4())
        ).error_code
        == "node_identity_mismatch"
    )


def test_oversized_user_payload_stops_before_connection(
    agent_endpoint: tuple[NodeConnection, list[object]],
) -> None:
    connection, _ = agent_endpoint
    limited = replace(connection, runtime=replace(connection.runtime, max_body_bytes=1))
    user = VlessUser(XrayUserIdentity("inbound", "user"), uuid4())
    result = NativeAgentGateway().apply_vless(limited, user)
    assert result.succeeded is False
    assert result.error_code == "request_body_limit"
