from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigurationError(RuntimeError):
    """Raised when startup configuration is unsafe or incomplete."""


def _admin_ids(raw: str | None) -> frozenset[int]:
    if not raw:
        return frozenset()
    try:
        return frozenset(int(value.strip()) for value in raw.split(",") if value.strip())
    except ValueError as exc:
        raise ConfigurationError("ADMIN_IDS باید شامل شناسه‌های عددی باشد.") from exc


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration with one supported MySQL persistence URL."""

    bot_token: str | None
    database_url: str
    admin_ids: frozenset[int]
    support_username: str | None

    @classmethod
    def from_environment(cls, *, require_token: bool = True) -> Settings:
        token = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or "").strip() or None
        if require_token and not token:
            raise ConfigurationError("TELEGRAM_BOT_TOKEN تنظیم نشده است؛ بات شروع نشد.")
        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url.startswith("mysql+aiomysql://"):
            raise ConfigurationError("DATABASE_URL باید با mysql+aiomysql:// شروع شود.")
        return cls(
            bot_token=token,
            database_url=database_url,
            admin_ids=_admin_ids(os.getenv("ADMIN_IDS") or os.getenv("ADMIN_TELEGRAM_IDS")),
            support_username=os.getenv("SUPPORT_USERNAME", "").lstrip("@") or None,
        )
