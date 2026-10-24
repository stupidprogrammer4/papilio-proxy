"""Real worker-owned failed work and an uncertain reply for the native browser gate."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import UUID

from conftest import until
from django.db import connection
from rest_framework.test import APIClient
from telegram_server import TelegramServer
from test_bots import bot_input

from papilio_panel.modules.shop.models import InboxWork, OutgoingMessage


@dataclass(frozen=True)
class RecoveryBrowserState:
    bot_id: UUID
    work_id: UUID
    message_id: UUID
    message_ciphertext: bytes = field(repr=False)


@contextmanager
def browser_recovery_scenario(owner: APIClient) -> Iterator[RecoveryBrowserState]:
    assert str(connection.settings_dict["NAME"]).startswith("test_")
    server = TelegramServer()
    server.scripted_replies["sendMessage"] = [(500, {"ok": False})]
    with server.running() as address:
        created = owner.post(
            "/api/v1/bots",
            bot_input(
                "Browser recovery bot",
                "345678901:placeholder-not-a-real-recovery-token",
            )
            | {
                "runtime": {
                    "api_base_url": address,
                    "poll_timeout_seconds": 1,
                    "http_timeout_seconds": 6,
                },
                "schedule": {"enabled": True, "interval_seconds": 1},
            },
            format="json",
        )
        assert created.status_code == 202
        bot_id = UUID(created.json()["id"])
        root = f"/api/v1/bots/{bot_id}"
        definition = owner.get("/api/v1/bot-shop-defaults").json() | {
            "enabled": True,
            "locale": "en",
            "public_origin": "http://panel.example.invalid",
        }
        assert owner.post(root + "/shop", definition, format="json").status_code == 201
        until(lambda: owner.get(root).json()["verified"] is True)
        server.push(1, "/start", chat_id=987654)
        until(
            lambda: OutgoingMessage.objects.filter(
                bot_id=bot_id,
                event__update_id=1,
                status="ambiguous",
            ).exists(),
            timeout=12,
        )
        server.push(2, "/topup not-an-amount", chat_id=987654)
        until(
            lambda: InboxWork.objects.filter(
                event__bot_id=bot_id,
                event__update_id=2,
                status="failed",
            ).exists(),
            timeout=12,
        )
        work = InboxWork.objects.get(event__bot_id=bot_id, event__update_id=2)
        message = OutgoingMessage.objects.get(bot_id=bot_id, event__update_id=1)
        yield RecoveryBrowserState(bot_id, work.id, message.id, bytes(message.payload_ciphertext))
