"""A committed payment notification survives an actual test-owned broker outage."""

import os
import subprocess

import pytest
from conftest import until
from telegram_server import TelegramServer
from test_bots import bot_input
from test_manual_payments import decision
from test_nodes import owner_client

from papilio_panel.modules.payments.models import Invoice, PaymentDecisionEvent
from papilio_panel.modules.shop.models import OutgoingMessage, ShopCustomer

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.runtime]


@pytest.mark.timeout(120)
def test_payment_event_recovers_without_reposting_credit(runtime: None) -> None:
    container = os.environ.get("PAPILIO_TEST_BROKER_CONTAINER")
    if not container:
        pytest.skip("Explicitly test-owned RabbitMQ is required for this fault boundary.")
    server = TelegramServer()
    with server.running() as address:
        owner = owner_client("event-fault-owner")
        created = owner.post(
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
        root = f"/api/v1/bots/{bot['id']}"
        definition = owner.get("/api/v1/bot-shop-defaults").json() | {
            "enabled": True,
            "locale": "en",
            "public_origin": "http://panel.example.invalid",
        }
        assert owner.post(root + "/shop", definition, format="json").status_code == 201
        assert (
            owner.post(
                "/api/v1/payment-settings",
                {"recipient": "Controlled operator", "destination": "CONTROLLED-RECOVERY-ACCOUNT"},
                format="json",
            ).status_code
            == 201
        )
        until(lambda: owner.get(root).json()["verified"] is True)
        server.push(10, "/start", chat_id=987654)
        until(
            lambda: any(values["text"].startswith("Welcome") for _, values in server.messages),
            timeout=12,
        )
        customer = ShopCustomer.objects.get(telegram_user_id=987654)
        server.push(11, "/topup 1000", chat_id=987654)
        until(lambda: Invoice.objects.filter(customer_id=customer.customer_id).exists(), timeout=12)
        invoice = Invoice.objects.get(customer_id=customer.customer_id)
        invoice_root = f"/api/v1/invoices/{invoice.id}"
        subprocess.run(
            ["docker", "exec", container, "rabbitmqctl", "stop_app"],
            check=True,
            capture_output=True,
            timeout=30,
        )
        try:
            values = decision(owner.get(invoice_root).json())
            accepted = owner.post(invoice_root + "/decisions", values, format="json")
            assert accepted.status_code == 201
            assert owner.post(invoice_root + "/decisions", values, format="json").status_code == 200
            invoice.refresh_from_db()
            assert invoice.status == "settled"
            event = PaymentDecisionEvent.objects.get(decision__invoice=invoice)
            assert event.processed_at is None and event.dispatched_at is None
            assert not OutgoingMessage.objects.filter(source_event=event).exists()
            wallet = f"/api/v1/customer-accounts/{customer.customer_id}/wallet"
            assert owner.get(wallet).json()["balance_minor"] == "1000"
        finally:
            subprocess.run(
                ["docker", "exec", container, "rabbitmqctl", "start_app"],
                check=True,
                capture_output=True,
                timeout=30,
            )
        until(
            lambda: OutgoingMessage.objects.filter(source_event=event, status="sent").exists(),
            timeout=35,
        )
        event.refresh_from_db()
        assert event.outcome == "queued" and event.processed_at is not None
        assert OutgoingMessage.objects.filter(source_event=event).count() == 1
        assert (
            len(
                [
                    values
                    for _, values in server.messages
                    if values["text"].startswith("Payment approved:")
                    and values["chat_id"] == 987654
                ]
            )
            == 1
        )
        assert owner.get(wallet).json()["balance_minor"] == "1000"
        assert owner.get(wallet + "/entries").json()["count"] == 1
