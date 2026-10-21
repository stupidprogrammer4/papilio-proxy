"""Validate bootstrap settings without reading runtime or legacy files."""

import os
import re
from urllib.parse import parse_qs, unquote, urlsplit

from django.core.exceptions import ImproperlyConfigured


def required(name: str) -> str:
    """Read a required value without including its content in errors."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"{name} must be configured.")
    return value


def positive_integer(name: str, default: int) -> int:
    """Read a positive integer bootstrap setting."""
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as error:
        raise ImproperlyConfigured(f"{name} must be a positive integer.") from error
    if value <= 0:
        raise ImproperlyConfigured(f"{name} must be a positive integer.")
    return value


def boolean(name: str, default: bool) -> bool:
    """Reject misspelled flags rather than silently changing security behavior."""
    raw = os.environ.get(name, "true" if default else "false").lower()
    if raw not in {"true", "false", "1", "0"}:
        raise ImproperlyConfigured(f"{name} must be true/false or 1/0.")
    return raw in {"true", "1"}


def transport_scheme(environment: str) -> str:
    """Select browser transport independently of the deployment environment."""
    scheme = os.environ.get(
        "PAPILIO_TRANSPORT_SCHEME", "https" if environment == "production" else "http"
    )
    if scheme not in {"http", "https"}:
        raise ImproperlyConfigured("PAPILIO_TRANSPORT_SCHEME must be http or https.")
    return scheme


def deployment_identity() -> tuple[str, str]:
    """Return the validated environment and instance namespace."""
    environment = os.environ.get("PAPILIO_ENV", "dev")
    instance = os.environ.get("PAPILIO_INSTANCE", "default")
    if environment not in {"dev", "test", "sandbox", "production"}:
        raise ImproperlyConfigured("PAPILIO_ENV must be dev, test, sandbox or production.")
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", instance) is None:
        raise ImproperlyConfigured("PAPILIO_INSTANCE must be a short lowercase identifier.")
    return environment, instance


def postgres_database() -> dict[str, object]:
    """Build a PostgreSQL-only Django configuration from an explicit URL."""
    parsed = urlsplit(required("DATABASE_URL"))
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ImproperlyConfigured("DATABASE_URL must use PostgreSQL.")
    if not parsed.hostname or not parsed.username or not parsed.path.strip("/"):
        raise ImproperlyConfigured("DATABASE_URL requires host, username and database name.")
    options: dict[str, object] = {
        "connect_timeout": positive_integer("PAPILIO_DB_CONNECT_TIMEOUT", 5),
    }
    sslmode = parse_qs(parsed.query).get("sslmode")
    if sslmode:
        options["sslmode"] = sslmode[0]
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.strip("/")),
        "USER": unquote(parsed.username),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname,
        "PORT": parsed.port or 5432,
        "CONN_MAX_AGE": 0,
        "OPTIONS": options,
    }
