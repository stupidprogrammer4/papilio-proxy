import math
import os
from dataclasses import dataclass

from papilio_telegram.checkout import CheckoutDraftLimits


@dataclass(frozen=True, slots=True)
class BotApiLimits:
    max_response_bytes: int
    max_connections: int
    read_buffer_bytes: int
    keepalive_seconds: int
    dns_cache_seconds: int

    def __post_init__(self) -> None:
        if (
            min(
                self.max_response_bytes,
                self.max_connections,
                self.read_buffer_bytes,
                self.keepalive_seconds,
                self.dns_cache_seconds,
            )
            <= 0
        ):
            raise ValueError("API capacities must be positive")
        if self.read_buffer_bytes > self.max_response_bytes:
            raise ValueError("Read buffer exceeds response capacity")


@dataclass(frozen=True, slots=True)
class BotSettings:
    api_limits: BotApiLimits
    checkout_limits: CheckoutDraftLimits
    webhook_max_inflight: int
    webhook_processing_timeout_seconds: float
    webhook_max_request_bytes: int
    notification_delivery_enabled: bool
    notification_delivery_key: str | None
    notification_send_timeout_seconds: int
    notification_lease_margin_seconds: int
    notification_max_request_bytes: int
    telegram_token: str
    webhook_secret: str
    webhook_public_url: str | None
    api_url: str
    api_key: str
    api_timeout_seconds: float
    listen_host: str
    listen_port: int

    @classmethod
    def from_environment(cls) -> "BotSettings":
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        webhook_secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
        api_key = os.environ.get("PAPILIO_BOT_KEY", "")
        required = (
            "BOT_CHECKOUT_MAX_DRAFTS",
            "BOT_CHECKOUT_DRAFT_SECONDS",
            "BOT_CHECKOUT_HISTORY_PAGE_SIZE",
            "PAPILIO_API_MAX_RESPONSE_BYTES",
            "PAPILIO_API_READ_BUFFER_BYTES",
            "PAPILIO_API_MAX_CONNECTIONS",
            "PAPILIO_API_KEEPALIVE_SECONDS",
            "PAPILIO_API_DNS_CACHE_SECONDS",
            "BOT_WEBHOOK_PROCESSING_TIMEOUT_SECONDS",
            "BOT_WEBHOOK_MAX_INFLIGHT",
            "BOT_WEBHOOK_MAX_REQUEST_BYTES",
            "PAPILIO_API_URL",
            "PAPILIO_API_TIMEOUT_SECONDS",
            "BOT_LISTEN_HOST",
            "BOT_LISTEN_PORT",
            "NOTIFICATION_DELIVERY_ENABLED",
            "NOTIFICATION_SEND_TIMEOUT_SECONDS",
            "NOTIFICATION_LEASE_MARGIN_SECONDS",
            "NOTIFICATION_MAX_REQUEST_BYTES",
        )
        if (
            not token
            or not webhook_secret
            or not api_key
            or any(not os.environ.get(name) for name in required)
        ):
            raise ValueError(
                "Configure Telegram, Papilio API and listen settings"
            )
        mode = os.environ["NOTIFICATION_DELIVERY_ENABLED"].lower()
        key = os.environ.get("NOTIFICATION_DELIVERY_KEY") or None
        if (
            mode not in {"true", "false"}
            or mode == "true"
            and (not key or not key.isascii() or len(key) < 32)
        ):
            raise ValueError(
                "Configure an explicit delivery mode and private key"
            )
        timeout = int(os.environ["NOTIFICATION_SEND_TIMEOUT_SECONDS"])
        margin = int(os.environ["NOTIFICATION_LEASE_MARGIN_SECONDS"])
        capacity = int(os.environ["NOTIFICATION_MAX_REQUEST_BYTES"])
        if min(timeout, margin, capacity) <= 0:
            raise ValueError("Delivery capacities must be positive")
        deadline = float(os.environ["BOT_WEBHOOK_PROCESSING_TIMEOUT_SECONDS"])
        inflight = int(os.environ["BOT_WEBHOOK_MAX_INFLIGHT"])
        request_bytes = int(os.environ["BOT_WEBHOOK_MAX_REQUEST_BYTES"])
        if (
            not math.isfinite(deadline)
            or min(inflight, request_bytes, deadline) <= 0
        ):
            raise ValueError("Webhook capacities must be positive")
        return cls(
            checkout_limits=CheckoutDraftLimits(
                max_entries=int(os.environ["BOT_CHECKOUT_MAX_DRAFTS"]),
                lifetime_seconds=int(os.environ["BOT_CHECKOUT_DRAFT_SECONDS"]),
                history_page_size=int(
                    os.environ["BOT_CHECKOUT_HISTORY_PAGE_SIZE"]
                ),
            ),
            api_limits=BotApiLimits(
                max_response_bytes=int(
                    os.environ["PAPILIO_API_MAX_RESPONSE_BYTES"]
                ),
                max_connections=int(os.environ["PAPILIO_API_MAX_CONNECTIONS"]),
                read_buffer_bytes=int(
                    os.environ["PAPILIO_API_READ_BUFFER_BYTES"]
                ),
                keepalive_seconds=int(
                    os.environ["PAPILIO_API_KEEPALIVE_SECONDS"]
                ),
                dns_cache_seconds=int(
                    os.environ["PAPILIO_API_DNS_CACHE_SECONDS"]
                ),
            ),
            webhook_max_inflight=inflight,
            webhook_processing_timeout_seconds=deadline,
            webhook_max_request_bytes=request_bytes,
            notification_delivery_enabled=mode == "true",
            notification_delivery_key=key,
            notification_send_timeout_seconds=timeout,
            notification_lease_margin_seconds=margin,
            notification_max_request_bytes=capacity,
            telegram_token=token,
            webhook_secret=webhook_secret,
            webhook_public_url=os.environ.get("TELEGRAM_WEBHOOK_PUBLIC_URL")
            or None,
            api_url=os.environ["PAPILIO_API_URL"],
            api_key=api_key,
            api_timeout_seconds=float(
                os.environ["PAPILIO_API_TIMEOUT_SECONDS"]
            ),
            listen_host=os.environ["BOT_LISTEN_HOST"],
            listen_port=int(os.environ["BOT_LISTEN_PORT"]),
        )
