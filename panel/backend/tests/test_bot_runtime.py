"""Actual Beat/RabbitMQ/prefork workers with an external Telegram API double."""

from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from celery.canvas import Signature
from conftest import until
from telegram_server import TelegramServer
from test_bots import TEST_TOKEN, bot_input
from test_nodes import owner_client

from papilio_panel.modules.bots.domain import BotTaskName
from papilio_panel.modules.bots.models import Bot, TelegramInbox

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.runtime]


def test_scheduler_worker_pairs_bot_and_paused_schedule_rejects_delivered_work(
    runtime: None,
) -> None:
    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        submitted = client.post(
            "/api/v1/bots",
            bot_input()
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
        assert submitted.status_code == 202
        bot = submitted.json()
        root = f"/api/v1/bots/{bot['id']}"
        until(lambda: client.get(root).json()["verified"] is True)
        ciphertext = bytes(Bot.objects.get(pk=bot["id"]).token_ciphertext)
        assert TEST_TOKEN.encode() not in ciphertext
        assert b"placeholder" not in ciphertext
        grant = client.post(root + "/pairing")
        assert grant.status_code == 200
        parameter = parse_qs(urlsplit(grant.json()["url"]).query)["start"][0]
        server.push(20, "/start " + parameter)
        until(lambda: client.get(root).json()["admin_chat_id"] == 456789)
        until(
            lambda: any(
                method == "getUpdates" and values["offset"] == 21 for method, values in server.calls
            )
        )
        assert TelegramInbox.objects.filter(bot_id=bot["id"], update_id=20).count() == 1
        assert client.get(root).json()["next_update_id"] == "21"
        current = client.get(root).json()
        paused = client.put(
            root,
            {
                "label": current["label"],
                "expected_revision": current["revision"],
                "runtime": current["runtime"],
                "schedule": {"enabled": False, "interval_seconds": 7},
            },
            format="json",
        )
        assert paused.status_code == 200
        # A native probe behind the replay establishes that the I/O queue progressed.
        Signature(BotTaskName.POLL.value, kwargs={"bot_id": bot["id"]}).apply_async()
        calls = len(server.calls)
        sentinel = client.post(
            "/api/v1/system/probes", {"kind": "io", "request_key": str(uuid4())}, format="json"
        ).json()
        until(lambda: client.get(sentinel["status_url"]).json()["status"] == "succeeded")
        assert len(server.calls) == calls
        assert bytes(Bot.objects.get(pk=bot["id"]).token_ciphertext) == ciphertext
        assert client.get(root).json()["schedule"] == {"enabled": False, "interval_seconds": 7}
        assert {method for method, _ in server.calls} == {"getMe", "getWebhookInfo", "getUpdates"}
