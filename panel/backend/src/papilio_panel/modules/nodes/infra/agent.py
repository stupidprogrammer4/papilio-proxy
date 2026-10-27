"""Native HTTPS node observations, restricted to the issued identity and authority."""

import http.client
import json
import os
import ssl
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit
from uuid import UUID

from cryptography import x509

from ..domain import (
    MutationObservation,
    NodeConnection,
    NodeTrafficCounter,
    NodeTrafficSnapshot,
    ProbeObservation,
    TrafficObservation,
    VlessUser,
    XrayUserIdentity,
)


@dataclass(frozen=True)
class AgentReply:
    status: int = 0
    content: bytes = b""
    error_code: str | None = None


class NodeIdentityMismatch(Exception):
    """The verified TLS peer belongs to a different node or deployment."""


def write_private(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(content)


def peer_matches(connection: http.client.HTTPSConnection, node: NodeConnection) -> bool:
    if not isinstance(connection.sock, ssl.SSLSocket):
        return False
    der = connection.sock.getpeercert(binary_form=True)
    if der is None:
        return False
    certificate = x509.load_der_x509_certificate(der)
    names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    identities = names.get_values_for_type(x509.UniformResourceIdentifier)
    return identities == [f"spiffe://papilio/{node.deployment_id}/nodes/{node.node_id}/agent"]


def status_observation(content: bytes, node_id: UUID) -> ProbeObservation:
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("The node status must be an object.")
    identifier, protocol, core = (
        value.get("node_id"),
        value.get("protocol_version"),
        value.get("core"),
    )
    if not isinstance(identifier, str) or type(protocol) is not int or not isinstance(core, dict):
        raise ValueError("The node status fields have invalid types.")
    if UUID(identifier) != node_id or protocol != 1:
        return ProbeObservation(reachable=False, error_code="node_identity_mismatch")
    uptime = core.get("uptime_seconds")
    if type(uptime) is not int or not 0 <= uptime <= 4294967295:
        raise ValueError("The core uptime is invalid.")
    return ProbeObservation(reachable=True, uptime_seconds=uptime)


def traffic_snapshot(content: bytes, node_id: UUID) -> NodeTrafficSnapshot:
    value = json.loads(content)
    if not isinstance(value, dict) or not isinstance(value.get("traffic"), dict):
        raise ValueError("The node traffic response must contain a snapshot.")
    if UUID(value.get("node_id", "")) != node_id:
        raise ValueError("The node traffic identity does not match.")
    snapshot = value["traffic"]
    uptime = snapshot.get("uptime_seconds")
    counters = snapshot.get("counters")
    if type(uptime) is not int or not 0 <= uptime <= 4294967295 or not isinstance(counters, list):
        raise ValueError("The node traffic snapshot has invalid fields.")
    result: list[NodeTrafficCounter] = []
    identities: set[tuple[str, str]] = set()
    for counter in counters:
        if not isinstance(counter, dict):
            raise ValueError("The node traffic counter must be an object.")
        email, direction, byte_count = (
            counter.get("email"),
            counter.get("direction"),
            counter.get("bytes"),
        )
        if (
            not isinstance(email, str)
            or not email
            or len(email) > 64
            or direction not in {"uplink", "downlink"}
            or type(byte_count) is not int
            or not 0 <= byte_count <= 9223372036854775807
            or (email, direction) in identities
        ):
            raise ValueError("The node traffic counter has invalid values.")
        identities.add((email, direction))
        result.append(NodeTrafficCounter(email, direction, byte_count))
    return NodeTrafficSnapshot(tuple(result), uptime)


class NativeAgentGateway:
    def check(self, connection: NodeConnection) -> ProbeObservation:
        reply = self._exchange(connection, "GET", f"/v1/nodes/{connection.node_id}/status")
        if reply.error_code is not None:
            return ProbeObservation(reachable=False, error_code=reply.error_code)
        if reply.status != 200:
            return ProbeObservation(reachable=False, error_code="node_not_ready")
        try:
            result = status_observation(reply.content, connection.node_id)
        except (ValueError, TypeError, KeyError):
            result = ProbeObservation(reachable=False, error_code="invalid_node_response")
        return result

    def traffic(self, connection: NodeConnection) -> TrafficObservation:
        reply = self._exchange(connection, "GET", f"/v1/nodes/{connection.node_id}/xray/traffic")
        if reply.error_code is not None:
            return TrafficObservation(None, reply.error_code)
        if reply.status != 200:
            return TrafficObservation(None, "node_not_ready")
        try:
            result = TrafficObservation(traffic_snapshot(reply.content, connection.node_id))
        except (ValueError, TypeError, KeyError):
            result = TrafficObservation(None, "invalid_node_response")
        return result

    def apply_vless(self, connection: NodeConnection, user: VlessUser) -> MutationObservation:
        payload = json.dumps(
            {
                "inbound_tag": user.identity.inbound_tag,
                "uuid": str(user.identifier),
                "flow": user.flow,
                "level": user.level,
            }
        ).encode()
        path = f"/v1/nodes/{connection.node_id}/xray/users/{quote(user.identity.email, safe='')}"
        reply = self._exchange(connection, "PUT", path, payload)
        return mutation_observation(reply, connection.node_id)

    def remove_xray(
        self, connection: NodeConnection, identity: XrayUserIdentity
    ) -> MutationObservation:
        path = f"/v1/nodes/{connection.node_id}/xray/users/{quote(identity.email, safe='')}"
        query = urlencode({"inbound_tag": identity.inbound_tag})
        reply = self._exchange(connection, "DELETE", f"{path}?{query}")
        return mutation_observation(reply, connection.node_id)

    def _exchange(
        self, node: NodeConnection, method: str, path: str, payload: bytes | None = None
    ) -> AgentReply:
        if payload is not None and len(payload) > node.runtime.max_body_bytes:
            return AgentReply(error_code="request_body_limit")
        try:
            reply = self._send(node, method, path, payload)
        except NodeIdentityMismatch:
            reply = AgentReply(error_code="node_identity_mismatch")
        except (ssl.SSLError, x509.ExtensionNotFound):
            reply = AgentReply(error_code="tls_rejected")
        except (OSError, http.client.HTTPException):
            reply = AgentReply(error_code="connection_failed")
        except (ValueError, TypeError):
            reply = AgentReply(error_code="invalid_node_response")
        return reply

    def _send(
        self, node: NodeConnection, method: str, path: str, payload: bytes | None
    ) -> AgentReply:
        endpoint = urlsplit(node.endpoint_url)
        with tempfile.TemporaryDirectory(prefix="papilio-node-") as directory:
            certificate, key = Path(directory) / "client.crt", Path(directory) / "client.key"
            write_private(certificate, node.credentials.control_certificate)
            write_private(key, node.credentials.private_keys.control)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.minimum_version = ssl.TLSVersion.TLSv1_3
            context.load_verify_locations(cadata=node.credentials.authority_certificate)
            context.load_cert_chain(str(certificate), str(key))
            connection = http.client.HTTPSConnection(
                endpoint.hostname or "",
                endpoint.port or 443,
                context=context,
                timeout=node.runtime.request_timeout_seconds,
            )
            try:
                connection.connect()
                if not peer_matches(connection, node):
                    raise NodeIdentityMismatch
                headers = {"Content-Type": "application/json"} if payload is not None else {}
                connection.request(method, path, body=payload, headers=headers)
                response = connection.getresponse()
                maximum = node.runtime.max_grpc_reply_bytes
                content = response.read(maximum + 1)
                if len(content) > maximum:
                    return AgentReply(error_code="node_response_limit")
                return AgentReply(status=response.status, content=content)
            finally:
                connection.close()


def mutation_observation(reply: AgentReply, node_id: UUID) -> MutationObservation:
    if reply.error_code is not None:
        return MutationObservation(node_id, succeeded=False, error_code=reply.error_code)
    try:
        result = read_mutation(reply, node_id)
    except (ValueError, TypeError, KeyError):
        result = MutationObservation(node_id, succeeded=False, error_code="invalid_node_response")
    return result


def read_mutation(reply: AgentReply, node_id: UUID) -> MutationObservation:
    value = json.loads(reply.content)
    if not isinstance(value, dict):
        raise ValueError("The node mutation reply must be an object.")
    if reply.status != 200:
        expected_codes = {
            400: "invalid_input",
            404: "node_not_found",
            409: "unsupported_account",
            408: "request_cancelled",
            502: "core_rejected",
            504: "core_timeout",
        }
        allowed = (
            {"core_unavailable", "core_resource_limit"}
            if reply.status == 503
            else {expected_codes.get(reply.status)}
        )
        code = value.get("code")
        if not isinstance(code, str) or code not in allowed:
            raise ValueError("The node returned an unrecognized error.")
        return MutationObservation(node_id, succeeded=False, error_code=code)
    identifier, changed = value.get("node_id"), value.get("changed")
    if not isinstance(identifier, str) or type(changed) is not bool:
        raise ValueError("The node mutation identity or result has an invalid type.")
    if UUID(identifier) != node_id:
        return MutationObservation(node_id, succeeded=False, error_code="node_identity_mismatch")
    return MutationObservation(node_id, succeeded=True, changed=changed)
