"""Pure configuration normalization and input identities."""

import hashlib
import ipaddress
import json
import re
from dataclasses import asdict, replace
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

from papilio_panel.shared.errors import InvalidInput

from ..domain import BotChange, BotCreate, BotRuntime, BotSchedule


def token_digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def create_digest(values: BotCreate) -> str:
    content = {
        "label": values.label,
        "token_digest": token_digest(values.token),
        "runtime": asdict(values.runtime),
        "schedule": asdict(values.schedule),
    }
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def api_origin(value: str) -> str:
    try:
        URLValidator(schemes=["https", "http"])(value)
        parts = urlsplit(value)
        host = parts.hostname
        if (
            not host
            or parts.username
            or parts.password
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
        ):
            raise InvalidInput("Choose an API origin without credentials, query or path.")
        if parts.scheme == "http" and not ipaddress.ip_address(host).is_loopback:
            raise InvalidInput("Plain HTTP is permitted only for a literal loopback API server.")
        port = parts.port if parts.port is not None else (443 if parts.scheme == "https" else 80)
        if not 1 <= port <= 65535:
            raise InvalidInput("Choose an API port from 1 to 65535.")
        host = host.encode("idna").decode("ascii").lower()
    except (ValidationError, ValueError, UnicodeError) as error:
        raise InvalidInput(
            "Choose a valid HTTPS API origin or literal HTTP loopback server."
        ) from error
    authority = f"[{host}]" if ":" in host else host
    return f"{parts.scheme}://{authority}:{port}"


def validated_runtime(values: BotRuntime, schedule: BotSchedule) -> BotRuntime:
    numbers = (
        values.poll_timeout_seconds,
        values.http_timeout_seconds,
        values.max_response_bytes,
        values.pairing_ttl_seconds,
        values.failure_retry_seconds,
        schedule.interval_seconds,
    )
    if any(type(number) is not int or not 1 <= number <= 2147483647 for number in numbers):
        raise InvalidInput(
            "Bot timeouts, limits and intervals must be positive PostgreSQL integers."
        )
    if 3 * values.http_timeout_seconds + 30 > 2147483647:
        raise InvalidInput("The derived task expiry must fit the native Beat integer field.")
    if values.http_timeout_seconds < values.poll_timeout_seconds + 5:
        raise InvalidInput("HTTP timeout must exceed polling time by at least five seconds.")
    if type(values.update_limit) is not int or not 1 <= values.update_limit <= 100:
        raise InvalidInput("Telegram permits between 1 and 100 updates per call.")
    if type(schedule.enabled) is not bool:
        raise InvalidInput("Choose an explicit enabled state.")
    return replace(values, api_base_url=api_origin(values.api_base_url))


def validate_token(value: str) -> None:
    if not 20 <= len(value) <= 512 or re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", value) is None:
        raise InvalidInput("Enter a valid bot token.")


def validated_create(values: BotCreate) -> BotCreate:
    validate_token(values.token)
    label = values.label.strip()
    if not 1 <= len(label) <= 80:
        raise InvalidInput("Choose a bot label of up to 80 characters.")
    runtime = validated_runtime(values.runtime, values.schedule)
    return replace(values, label=label, runtime=runtime)


def validated_change(values: BotChange) -> BotChange:
    if values.token is not None:
        validate_token(values.token)
    label = values.label.strip()
    if not 1 <= len(label) <= 80 or not 1 <= values.expected_revision < 9223372036854775807:
        raise InvalidInput("Choose a valid bot label and revision.")
    runtime = validated_runtime(values.runtime, values.schedule)
    return replace(values, label=label, runtime=runtime)
