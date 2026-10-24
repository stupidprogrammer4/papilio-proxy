"""Scheduled bot purchase delivers a usable subscription through the native core."""

import base64
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from conftest import until
from telegram_server import TelegramServer
from test_bots import bot_input
from test_node_user_control import native_control as native_control
from test_service_runtime import existing_owner_client
from xray_client import subscription_client

from papilio_panel.modules.nodes.domain import XrayApply
from papilio_panel.modules.orders.models import Order
from papilio_panel.modules.payments.models import Invoice, PaymentDecisionEvent, Receipt
from papilio_panel.modules.services.models import ServiceAccount
from papilio_panel.modules.shop.models import InboxWork, OutgoingMessage, ShopCustomer

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.runtime]


@pytest.mark.timeout(100)
@pytest.mark.parametrize("download_failures", [1, 6])
def test_bot_confirmation_worker_delivery_and_real_client(
    native_control: tuple[XrayApply, int, str], tmp_path: Path, download_failures: int
) -> None:
    node, data_port, binary = native_control
    owner = existing_owner_client()
    core = owner.post(
        "/api/v1/cores/xray",
        {"request_key": str(uuid4()), "node_id": str(node.node_id), "name": "Bot core"},
        format="json",
    )
    assert core.status_code == 201
    inbound = owner.post(
        f"/api/v1/cores/{core.json()['id']}/xray/inbounds",
        {
            "request_key": str(uuid4()),
            "tag": "vless-test",
            "public_host": "127.0.0.1",
            "port": data_port,
        },
        format="json",
    )
    assert inbound.status_code == 201
    product = owner.post(
        "/api/v1/products",
        {
            "request_key": str(uuid4()),
            "definition": {
                "name": "Bot paid product",
                "core_id": core.json()["id"],
                "inbound_id": inbound.json()["id"],
                "currency": "IRR",
                "price_minor": "1000",
            },
        },
        format="json",
    )
    assert product.status_code == 201
    server = TelegramServer()
    with server.running() as address:
        made = owner.post(
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
        assert made.status_code == 202
        bot = made.json()
        definition = owner.get("/api/v1/bot-shop-defaults").json() | {
            "enabled": True,
            "locale": "en",
            "retry_seconds": 1,
            "max_attempts": download_failures + 1,
            "public_origin": "http://panel.example.invalid",
        }
        assert (
            owner.post(f"/api/v1/bots/{bot['id']}/shop", definition, format="json").status_code
            == 201
        )
        until(lambda: owner.get(f"/api/v1/bots/{bot['id']}").json()["verified"] is True)
        identity = owner.get(f"/api/v1/bots/{bot['id']}").json()["telegram_id"]
        server.push(30, "/start", chat_id=987654)
        until(
            lambda: any(values["text"].startswith("Welcome") for _, values in server.messages),
            timeout=12,
        )
        customer = ShopCustomer.objects.get(telegram_user_id=987654)
        wallet = f"/api/v1/customer-accounts/{customer.customer_id}/wallet"
        settings = owner.post(
            "/api/v1/payment-settings",
            {
                "recipient": "Controlled bot account",
                "destination": "CONTROLLED-BOT-ACCOUNT",
                "instructions": "Send the exact amount and reply with evidence.",
            },
            format="json",
        )
        assert settings.status_code == 201
        pairing = owner.post(f"/api/v1/bots/{bot['id']}/pairing")
        assert pairing.status_code == 200
        parameter = parse_qs(urlsplit(pairing.json()["url"]).query)["start"][0]
        server.push(31, "/start " + parameter, chat_id=456789)
        until(lambda: owner.get(f"/api/v1/bots/{bot['id']}").json()["admin_chat_id"] == 456789)
        server.push(32, "/topup 2500", chat_id=987654)
        until(
            lambda: any(
                "Payment invoice:" in values["text"] and values["chat_id"] == 987654
                for _, values in server.messages
            ),
            timeout=12,
        )
        invoice = Invoice.objects.get(customer_id=customer.customer_id)
        invoice_message = next(
            identifier
            for identifier, values in server.messages
            if str(invoice.id) in values["text"] and "Payment invoice:" in values["text"]
        )
        server.files["photos/bank-proof.jpg"] = b"controlled-bot-receipt"
        server.file_statuses = [503] * download_failures
        server.push_photo(
            33,
            "bank-proof",
            chat_id=987654,
            reply_to_message_id=invoice_message,
            bot_id=identity,
            caption="Controlled transfer proof",
        )
        until(lambda: Receipt.objects.filter(invoice=invoice).exists(), timeout=25)
        until(
            lambda: any(
                str(invoice.id) in values["text"] and values["chat_id"] == 456789
                for _, values in server.messages
            ),
            timeout=12,
        )
        evidence = Receipt.objects.get(invoice=invoice)
        receipt_work = InboxWork.objects.get(event__bot_id=bot["id"], event__update_id=33)
        assert receipt_work.attempts == download_failures + 1 and receipt_work.status == "done"
        assert server.file_calls == ["photos/bank-proof.jpg"] * (download_failures + 1)
        assert bytes(evidence.content) == b"controlled-bot-receipt"
        assert owner.get(wallet).json()["balance_minor"] == "0"
        root = f"/api/v1/invoices/{invoice.id}"
        current_invoice = owner.get(root).json()
        approved = owner.post(
            root + "/decisions",
            {
                "request_key": str(uuid4()),
                "expected_revision": current_invoice["revision"],
                "action": "approve",
                "reason": "Confirmed in controlled statement boundary.",
                "receipt_id": str(evidence.id),
            },
            format="json",
        )
        assert approved.status_code == 201
        until(
            lambda: any(
                "Payment approved: 2500" in values["text"] and values["chat_id"] == 987654
                for _, values in server.messages
            ),
            timeout=12,
        )
        payment_event = PaymentDecisionEvent.objects.get(decision__invoice=invoice)
        assert payment_event.outcome == "queued" and payment_event.processed_at is not None
        until(
            lambda: OutgoingMessage.objects.filter(
                source_event=payment_event, status="sent"
            ).exists(),
            timeout=12,
        )
        assert owner.get(wallet).json()["balance_minor"] == "2500"
        assert not ShopCustomer.objects.filter(telegram_user_id=456789).exists()
        server.push_callback(
            34, f"offer:{UUID(product.json()['id']).hex}", chat_id=987654, bot_id=identity
        )
        until(
            lambda: any("Confirm to buy" in values["text"] for _, values in server.messages),
            timeout=12,
        )
        quote = next(values for _, values in server.messages if "Confirm to buy" in values["text"])
        callback = next(
            button["callback_data"]
            for row in quote["reply_markup"]["inline_keyboard"]
            for button in row
            if button["callback_data"].startswith("buy:")
        )
        server.push_callback(35, callback, chat_id=987654, bot_id=identity)
        server.push_callback(36, callback, chat_id=987654, bot_id=identity)
        until(
            lambda: (
                InboxWork.objects.filter(
                    event__bot_id=bot["id"], event__update_id__in=[35, 36], status="done"
                ).count()
                == 2
            ),
            timeout=15,
        )
        order = Order.objects.get()
        assert order.customer_id == customer.customer_id
        assert owner.get(wallet).json()["balance_minor"] == "1500"
        until(
            lambda: (
                ServiceAccount.objects.get(pk=order.service_id).status in {"succeeded", "failed"}
            ),
            timeout=15,
        )
        service = ServiceAccount.objects.get(pk=order.service_id)
        assert service.status == "succeeded" and service.worker_pid != os.getpid()
        server.push_callback(37, f"order:{order.id.hex}", chat_id=987654, bot_id=identity)
        until(
            lambda: any(
                "http://panel.example.invalid/api/v1/subscriptions?token=" in values["text"]
                for _, values in server.messages
            ),
            timeout=12,
        )
        delivery = next(
            values
            for _, values in server.messages
            if "http://panel.example.invalid/api/v1/subscriptions?token=" in values["text"]
        )
        assert delivery["chat_id"] == 987654
        url = next(
            line
            for line in delivery["text"].splitlines()
            if line.startswith("http://panel.example.invalid/")
        )
        parsed = urlsplit(url)
        subscription = owner.get(parsed.path + "?" + parsed.query)
        assert subscription.status_code == 200
        uri = base64.b64decode(subscription.content).decode().strip()
        with subscription_client(binary, tmp_path, uri) as probe:
            assert probe.fetch() == b"papilio-actual-subscription-client"
        assert Order.objects.count() == 1 and owner.get(wallet).json()["balance_minor"] == "1500"
