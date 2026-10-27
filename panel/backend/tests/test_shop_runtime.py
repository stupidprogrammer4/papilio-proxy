"""Actual Beat/worker conversation intake and durable external Telegram replies."""

import os
from uuid import uuid4

import pytest
from conftest import until
from telegram_server import TelegramServer
from test_bots import bot_input
from test_nodes import owner_client

from papilio_panel.modules.shop.models import InboxWork, OutgoingMessage, ShopCustomer

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.runtime]


@pytest.mark.timeout(75)
@pytest.mark.parametrize(
    ("locale", "welcome_prefix", "wallet_prefix"),
    [
        ("en", "Welcome,", "Wallet:"),
        ("fa", "987654، خوش آمدید", "موجودی کیف پول:"),
        ("ru", "Добро пожаловать", "Баланс кошелька:"),
        ("zh", "欢迎", "钱包余额："),
    ],
)
def test_native_scheduler_registers_customer_and_delivers_private_menu_and_wallet(
    runtime: None, locale: str, welcome_prefix: str, wallet_prefix: str
) -> None:
    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        created = client.post(
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
        assert created.status_code == 202
        bot = created.json()
        definition = client.get("/api/v1/bot-shop-defaults").json() | {
            "enabled": True,
            "locale": locale,
            "public_origin": "http://panel.example.invalid",
        }
        assert (
            client.post(f"/api/v1/bots/{bot['id']}/shop", definition, format="json").status_code
            == 201
        )
        until(lambda: client.get(f"/api/v1/bots/{bot['id']}").json()["verified"] is True)
        server.push(30, "/start", chat_id=987654)
        until(lambda: any(values["chat_id"] == 987654 for _, values in server.messages), timeout=12)
        menu = next(values for _, values in server.messages if values["chat_id"] == 987654)
        assert menu["text"].startswith(welcome_prefix)
        assert any(
            button["callback_data"] == "wallet"
            for row in menu["reply_markup"]["inline_keyboard"]
            for button in row
        )
        bound = ShopCustomer.objects.get(telegram_user_id=987654)
        work = InboxWork.objects.get(event__bot_id=bot["id"], event__update_id=30)
        assert work.status == "done" and work.worker_pid != os.getpid()
        message = OutgoingMessage.objects.get(event_id=work.event_id)
        assert message.status == "sent" and message.message_id is not None
        assert b"Welcome" not in bytes(message.payload_ciphertext)
        server.push(31, "/wallet", chat_id=987654)
        until(
            lambda: any(
                wallet_prefix in values["text"] and "0" in values["text"]
                for _, values in server.messages
            ),
            timeout=12,
        )
        assert (
            client.get(f"/api/v1/customer-accounts/{bound.customer_id}/wallet").json()[
                "balance_minor"
            ]
            == "0"
        )
        # A separately committed event replay must not create another customer or reply.
        from celery.canvas import Signature

        from papilio_panel.modules.shop.domain import ShopTaskName

        Signature(ShopTaskName.PROCESS.value, kwargs={"work_id": str(work.id)}).apply_async()
        sentinel = client.post(
            "/api/v1/system/probes", {"kind": "io", "request_key": str(uuid4())}, format="json"
        ).json()
        until(lambda: client.get(sentinel["status_url"]).json()["status"] == "succeeded")
        assert ShopCustomer.objects.count() == 1
        assert OutgoingMessage.objects.filter(event_id=work.event_id).count() == 1


@pytest.mark.timeout(75)
def test_native_worker_hides_and_rejects_disabled_shop_flows(runtime: None) -> None:
    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        created = client.post(
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
        assert created.status_code == 202
        bot = created.json()
        definition = client.get("/api/v1/bot-shop-defaults").json() | {
            "enabled": True,
            "locale": "en",
            "public_origin": "http://panel.example.invalid",
            "flows": {"catalogue": False, "wallet": False, "orders": True, "help": False},
        }
        assert (
            client.post(f"/api/v1/bots/{bot['id']}/shop", definition, format="json").status_code
            == 201
        )
        until(lambda: client.get(f"/api/v1/bots/{bot['id']}").json()["verified"] is True)
        server.push(40, "/start", chat_id=987655)
        until(lambda: any(values["chat_id"] == 987655 for _, values in server.messages), timeout=12)
        welcome = next(values for _, values in server.messages if values["chat_id"] == 987655)
        callbacks = {
            button["callback_data"]
            for row in welcome["reply_markup"]["inline_keyboard"]
            for button in row
        }
        assert "wallet" not in callbacks and "catalogue:1" not in callbacks

        server.push(41, "/wallet", chat_id=987655)
        until(
            lambda: any("not available" in values["text"] for _, values in server.messages),
            timeout=12,
        )
        server.push(42, "/products", chat_id=987655)
        until(
            lambda: sum("not available" in values["text"] for _, values in server.messages) == 2,
            timeout=12,
        )
        server.push(43, "/topup 100", chat_id=987655)
        until(
            lambda: sum("not available" in values["text"] for _, values in server.messages) == 3,
            timeout=12,
        )
