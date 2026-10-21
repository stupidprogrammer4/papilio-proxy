"""Pure node configuration validation and canonicalization."""

import ipaddress
from dataclasses import replace
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

from papilio_panel.shared.errors import InvalidInput

from ..domain import AgentRuntime, NodeDefinition


def endpoint_hostname(endpoint: str) -> str:
    hostname = urlsplit(endpoint).hostname
    if hostname is None:
        raise InvalidInput("The node endpoint needs a hostname.")
    return hostname


def canonical_endpoint(value: str) -> str:
    try:
        URLValidator(schemes=["https"])(value)
        parts = urlsplit(value)
        hostname = parts.hostname
        port = parts.port or 443
        if (
            hostname is None
            or parts.username
            or parts.password
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
        ):
            raise InvalidInput("Use an HTTPS node address without credentials or a path.")
        hostname = hostname.encode("idna").decode("ascii").lower()
    except (ValidationError, ValueError, UnicodeError) as error:
        raise InvalidInput("Use a valid HTTPS node endpoint.") from error
    authority = f"[{hostname}]" if ":" in hostname else hostname
    return f"https://{authority}:{port}"


def validate_socket(value: str, *, loopback: bool) -> None:
    try:
        parts = urlsplit("//" + value)
        port = parts.port
        if (
            port is None
            or not 1 <= port <= 65535
            or parts.path
            or parts.query
            or parts.fragment
            or parts.username
            or parts.password
        ):
            raise InvalidInput("Choose a valid host:port socket address.")
        if loopback and (
            parts.hostname is None or not ipaddress.ip_address(parts.hostname).is_loopback
        ):
            raise InvalidInput("The native Xray API must use a literal loopback address.")
    except ValueError as error:
        raise InvalidInput("Choose a valid socket address.") from error


def validate_runtime(values: AgentRuntime) -> None:
    integer_values = (
        values.request_timeout_seconds,
        values.read_header_timeout_seconds,
        values.idle_timeout_seconds,
        values.shutdown_timeout_seconds,
        values.max_grpc_reply_bytes,
    )
    if any(type(value) is not int or not 1 <= value <= 2147483647 for value in integer_values):
        raise InvalidInput("Runtime values must fit positive PostgreSQL integers.")
    if (
        type(values.max_body_bytes) is not int
        or not 1 <= values.max_body_bytes <= 9223372036854775807
    ):
        raise InvalidInput("The body limit must fit a positive BIGINT.")
    validate_socket(values.listen_address, loopback=False)
    validate_socket(values.xray_api_address, loopback=True)


def validated_definition(values: NodeDefinition) -> NodeDefinition:
    name = values.name.strip()
    if not 1 <= len(name) <= 80:
        raise InvalidInput("Choose a node name of up to 80 characters.")
    validate_runtime(values.runtime)
    policy = values.certificate_policy
    if any(
        type(value) is not int or not 1 <= value <= 2147483647
        for value in (policy.validity_seconds, policy.authority_validity_seconds)
    ):
        raise InvalidInput("Certificate lifetimes must fit positive PostgreSQL integers.")
    if (
        policy.authority_validity_seconds < policy.validity_seconds
        or not 0 <= policy.backdate_seconds <= 2147483647
    ):
        raise InvalidInput(
            "The authority must cover the leaf lifetime and backdating cannot be negative."
        )
    return replace(values, name=name, endpoint_url=canonical_endpoint(values.endpoint_url))
