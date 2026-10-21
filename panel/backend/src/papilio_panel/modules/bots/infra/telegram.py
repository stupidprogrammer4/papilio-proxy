"""Bounded native Telegram HTTP access with caller-safe failure codes."""

import http.client
import json
import re
from typing import Any
from urllib.parse import urlsplit

from ..domain import (
    BotInspection,
    IncomingMessage,
    IncomingUpdate,
    TelegramConnection,
    TelegramIdentity,
    UpdateBatch,
)
from .telegram_payload import retained_payload


class TelegramTransportError(Exception):
    def __init__(self, code: str, retry_after_seconds: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retry_after_seconds = retry_after_seconds


def integer(value: object, *, minimum: int = 0, maximum: int = 9223372036854775806) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Invalid Telegram integer.")
    return value


def incoming_message(payload: dict[str, Any]) -> IncomingMessage | None:
    message = payload.get("message")
    if not isinstance(message, dict):
        return None
    chat, sender, text = message.get("chat"), message.get("from"), message.get("text")
    if not isinstance(chat, dict) or not isinstance(sender, dict) or not isinstance(text, str):
        return None
    kind = chat.get("type")
    if not isinstance(kind, str):
        return None
    return IncomingMessage(
        chat_id=integer(chat.get("id"), minimum=-4503599627370495, maximum=4503599627370495),
        sender_id=integer(sender.get("id"), minimum=1, maximum=4503599627370495),
        chat_type=kind,
        text=text,
    )


def parse_updates(value: object, limit: int) -> tuple[IncomingUpdate, ...]:
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError("Invalid Telegram update batch.")
    updates: dict[int, IncomingUpdate] = {}
    sources: dict[int, dict[str, Any]] = {}
    for payload in value:
        if not isinstance(payload, dict):
            raise ValueError("Invalid Telegram update.")
        identifier = integer(payload.get("update_id"))
        update = IncomingUpdate(
            update_id=identifier,
            payload=retained_payload(payload),
            message=incoming_message(payload),
        )
        existing = sources.get(identifier)
        if existing is not None and existing != payload:
            raise ValueError("Conflicting duplicate Telegram update.")
        sources[identifier] = payload
        updates[identifier] = update
    return tuple(updates.values())


def invalid_constant(value: str) -> None:
    raise ValueError("Invalid JSON numeric constant.")


class NativeTelegramGateway:
    def _call(self, source: TelegramConnection, method: str, parameters: dict[str, Any]) -> Any:
        endpoint = urlsplit(source.runtime.api_base_url)
        client_class = (
            http.client.HTTPSConnection
            if endpoint.scheme == "https"
            else http.client.HTTPConnection
        )
        client = client_class(
            endpoint.hostname or "", endpoint.port, timeout=source.runtime.http_timeout_seconds
        )
        try:
            client.request(
                "POST",
                f"/bot{source.token}/{method}",
                body=json.dumps(parameters).encode(),
                headers={"Content-Type": "application/json"},
            )
            response = client.getresponse()
            body = response.read(source.runtime.max_response_bytes + 1)
            if len(body) > source.runtime.max_response_bytes:
                raise TelegramTransportError("response_limit")
            if response.status in {401, 404}:
                raise TelegramTransportError("invalid_token")
            if response.status == 409:
                raise TelegramTransportError("telegram_conflict")
            if response.status == 429:
                envelope = json.loads(body)
                retry = None
                if isinstance(envelope, dict) and isinstance(envelope.get("parameters"), dict):
                    value = envelope["parameters"].get("retry_after")
                    if type(value) is int and 1 <= value <= 2147483647:
                        retry = value
                raise TelegramTransportError("rate_limited", retry_after_seconds=retry)
            if response.status != 200:
                raise TelegramTransportError("telegram_unavailable")
            envelope = json.loads(body, parse_constant=invalid_constant)
            if (
                not isinstance(envelope, dict)
                or envelope.get("ok") is not True
                or "result" not in envelope
            ):
                raise TelegramTransportError("invalid_telegram_response")
            return envelope["result"]
        except (OSError, http.client.HTTPException):
            raise TelegramTransportError("connection_failed") from None
        except (ValueError, TypeError):
            raise TelegramTransportError("invalid_telegram_response") from None
        finally:
            client.close()

    def inspect(self, connection: TelegramConnection) -> BotInspection:
        try:
            identity = self._call(connection, "getMe", {})
            if not isinstance(identity, dict) or identity.get("is_bot") is not True:
                raise ValueError("Invalid Telegram identity.")
            identifier = integer(identity.get("id"), minimum=1, maximum=4503599627370495)
            username = identity.get("username")
            if (
                not isinstance(username, str)
                or re.fullmatch(r"[A-Za-z0-9_]{5,64}", username) is None
            ):
                raise ValueError("Invalid Telegram bot username.")
            webhook = self._call(connection, "getWebhookInfo", {})
            if not isinstance(webhook, dict) or not isinstance(webhook.get("url"), str):
                raise ValueError("Invalid Telegram webhook metadata.")
            result = BotInspection(
                identity=TelegramIdentity(id=identifier, username=username),
                webhook_configured=bool(webhook["url"]),
            )
        except TelegramTransportError as error:
            result = BotInspection(
                error_code=error.code, retry_after_seconds=error.retry_after_seconds
            )
        except (ValueError, TypeError):
            result = BotInspection(error_code="invalid_telegram_response")
        return result

    def updates(self, connection: TelegramConnection, next_update_id: int) -> UpdateBatch:
        try:
            values = self._call(
                connection,
                "getUpdates",
                {
                    "offset": next_update_id,
                    "limit": connection.runtime.update_limit,
                    "timeout": connection.runtime.poll_timeout_seconds,
                    "allowed_updates": ["message", "callback_query"],
                },
            )
            result = UpdateBatch(updates=parse_updates(values, connection.runtime.update_limit))
        except TelegramTransportError as error:
            result = UpdateBatch(
                error_code=error.code, retry_after_seconds=error.retry_after_seconds
            )
        except (ValueError, TypeError):
            result = UpdateBatch(error_code="invalid_telegram_response")
        return result
