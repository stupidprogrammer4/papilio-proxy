"""Bot configuration, Telegram facts and pairing data contracts."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class BotTaskName(StrEnum):
    POLL = "papilio.bots.poll"


@dataclass(frozen=True)
class BotRuntime:
    api_base_url: str = "https://api.telegram.org:443"
    poll_timeout_seconds: int = 10
    http_timeout_seconds: int = 15
    update_limit: int = 100
    max_response_bytes: int = 16777216
    pairing_ttl_seconds: int = 300
    failure_retry_seconds: int = 30


@dataclass(frozen=True)
class BotSchedule:
    enabled: bool = True
    interval_seconds: int = 10


@dataclass(frozen=True)
class BotDefaults:
    runtime: BotRuntime = field(default_factory=BotRuntime)
    schedule: BotSchedule = field(default_factory=BotSchedule)


@dataclass(frozen=True)
class BotCreate:
    actor_id: int
    request_key: UUID
    label: str
    token: str = field(repr=False)
    runtime: BotRuntime = field(default_factory=BotRuntime)
    schedule: BotSchedule = field(default_factory=BotSchedule)


@dataclass(frozen=True)
class BotChange:
    actor_id: int
    bot_id: UUID
    expected_revision: int
    label: str
    runtime: BotRuntime
    schedule: BotSchedule
    token: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class BotRead:
    id: UUID
    owner_id: int
    label: str
    revision: int
    runtime: BotRuntime
    schedule: BotSchedule
    telegram_id: int | None
    username: str | None
    verified: bool
    admin_chat_id: int | None
    last_poll_at: datetime | None
    last_error_code: str | None
    next_update_id: int
    retry_at: datetime | None


@dataclass(frozen=True)
class BotCreation:
    bot: BotRead
    input_digest: str


@dataclass(frozen=True)
class BotSearch:
    actor_id: int
    query: str = ""
    page: int = 1
    page_size: int = 20


@dataclass(frozen=True)
class BotPage:
    items: tuple[BotRead, ...]
    count: int
    page: int
    page_size: int


@dataclass(frozen=True)
class PairingSecret:
    parameter: str = field(repr=False)
    digest: str
    expires_at: datetime


@dataclass(frozen=True)
class PairingState:
    digest: str | None
    expires_at: datetime | None


@dataclass(frozen=True)
class PairingGrant:
    url: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True)
class TelegramIdentity:
    id: int
    username: str


@dataclass(frozen=True)
class IncomingMessage:
    chat_id: int
    sender_id: int
    chat_type: str
    text: str


@dataclass(frozen=True)
class IncomingUpdate:
    update_id: int
    payload: dict[str, Any]
    message: IncomingMessage | None


@dataclass(frozen=True)
class TelegramConnection:
    token: str = field(repr=False)
    runtime: BotRuntime


@dataclass(frozen=True)
class BotInspection:
    identity: TelegramIdentity | None = None
    webhook_configured: bool = False
    error_code: str | None = None
    retry_after_seconds: int | None = None


@dataclass(frozen=True)
class UpdateBatch:
    updates: tuple[IncomingUpdate, ...] = ()
    error_code: str | None = None
    retry_after_seconds: int | None = None


@dataclass(frozen=True)
class BotPollClaim:
    bot: BotRead
    lease_token: UUID
    connection: TelegramConnection = field(repr=False)


@dataclass(frozen=True)
class BotPollResult:
    identity: TelegramIdentity
    updates: tuple[IncomingUpdate, ...]
    next_update_id: int
    paired_chat_id: int | None
    pairing_digest: str | None
    observed_at: datetime


class BotCompletion(StrEnum):
    COMMITTED = "committed"
    STALE = "stale"
    IDENTITY_CONFLICT = "identity_conflict"
