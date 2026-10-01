from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


class ConfigurationError(RuntimeError):
    """Raised when startup configuration is unsafe or incomplete."""


def _admin_ids(raw: str | None) -> frozenset[int]:
    if not raw:
        return frozenset()
    try:
        return frozenset(int(value.strip()) for value in raw.split(",") if value.strip())
    except ValueError as exc:
        raise ConfigurationError("ADMIN_IDS باید شامل شناسه‌های عددی باشد.") from exc


def _subscription_public_base_url(raw: str | None) -> str | None:
    value = (raw or "").strip().rstrip("/")
    if not value:
        return None
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https" or not parsed.hostname
        or parsed.username or parsed.password or parsed.path
        or parsed.query or parsed.fragment
    ):
        raise ConfigurationError("SUBSCRIPTION_PUBLIC_BASE_URL باید ریشهٔ HTTPS دامنه باشد.")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration with one supported MySQL persistence URL."""

    bot_token: str | None
    database_url: str
    admin_ids: frozenset[int]
    support_username: str | None
    kpay_api_base_url: str | None
    credential_encryption_key: str | None
    subscription_public_base_url: str | None = None
    node_socket_path: str | None = None

    @classmethod
    def from_environment(cls, *, require_token: bool = True) -> Settings:
        token = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or "").strip() or None
        if require_token and not token:
            raise ConfigurationError("TELEGRAM_BOT_TOKEN تنظیم نشده است؛ بات شروع نشد.")
        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url.startswith("mysql+aiomysql://"):
            raise ConfigurationError("DATABASE_URL باید با mysql+aiomysql:// شروع شود.")
        node_socket = (os.getenv("XRAY_NODE_SOCKET") or "").strip()
        if node_socket and (not Path(node_socket).is_absolute() or ".." in Path(node_socket).parts):
            raise ConfigurationError("XRAY_NODE_SOCKET باید مسیر کامل و امن باشد.")
        return cls(
            bot_token=token,
            database_url=database_url,
            admin_ids=_admin_ids(os.getenv("ADMIN_IDS") or os.getenv("ADMIN_TELEGRAM_IDS")),
            support_username=os.getenv("SUPPORT_USERNAME", "").lstrip("@") or None,
            kpay_api_base_url=os.getenv("KPAY_API_BASE_URL", "").rstrip("/") or None,
            credential_encryption_key=os.getenv("CREDENTIAL_ENCRYPTION_KEY", "").strip() or None,
            subscription_public_base_url=_subscription_public_base_url(
                os.getenv("SUBSCRIPTION_PUBLIC_BASE_URL")
            ),
            node_socket_path=node_socket or None,
        )
