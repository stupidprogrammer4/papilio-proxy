"""Native HTTPS node observations, restricted to the issued identity and authority."""

import http.client
import json
import os
import ssl
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from cryptography import x509

from ..domain import NodeConnection, ProbeObservation


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


class NativeAgentGateway:
    def check(self, connection: NodeConnection) -> ProbeObservation:
        try:
            result = self._observe(connection)
        except (ssl.SSLError, x509.ExtensionNotFound):
            result = ProbeObservation(reachable=False, error_code="tls_rejected")
        except (OSError, http.client.HTTPException):
            result = ProbeObservation(reachable=False, error_code="connection_failed")
        except (ValueError, TypeError, KeyError):
            result = ProbeObservation(reachable=False, error_code="invalid_node_response")
        return result

    def _observe(self, node: NodeConnection) -> ProbeObservation:
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
                    return ProbeObservation(reachable=False, error_code="node_identity_mismatch")
                connection.request("GET", f"/v1/nodes/{node.node_id}/status")
                response = connection.getresponse()
                maximum = node.runtime.max_grpc_reply_bytes
                content = response.read(maximum + 1)
                if len(content) > maximum:
                    return ProbeObservation(reachable=False, error_code="node_response_limit")
                if response.status != 200:
                    return ProbeObservation(reachable=False, error_code="node_not_ready")
                return status_observation(content, node.node_id)
            finally:
                connection.close()
