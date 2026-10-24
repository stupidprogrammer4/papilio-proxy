"""Actual Beat/worker recovery of failed receipt work retains financial identity."""

from uuid import uuid4

import pytest
from conftest import until
from telegram_server import TelegramServer
from test_manual_payments import decision
from test_nodes import owner_client
from test_shop_payments import payment_bot
from test_shop_recovery import recovery

from papilio_panel.modules.payments.models import Receipt
from papilio_panel.modules.shop.models import InboxWork, WorkRecovery

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.runtime]


@pytest.mark.timeout(90)
def test_manual_work_retry_delivers_original_receipt_and_does_not_repeat_credit(
    runtime: None,
) -> None:
    server = TelegramServer()
    with server.running() as address:
        owner = owner_client("work-recovery-owner")
        bot, customer = payment_bot(owner, server, address)
        bot_root = f"/api/v1/bots/{bot}"
        current = owner.get(bot_root).json()
        assert (
            owner.put(
                bot_root,
                {
                    "expected_revision": current["revision"],
                    "label": current["label"],
                    "runtime": current["runtime"]
                    | {"poll_timeout_seconds": 1, "http_timeout_seconds": 6},
                    "schedule": {"enabled": True, "interval_seconds": 1},
                },
                format="json",
            ).status_code
            == 200
        )
        issued = owner.post(
            "/api/v1/invoices",
            {
                "request_key": str(uuid4()),
                "customer_id": customer,
                "base_amount_minor": "1000",
            },
            format="json",
        )
        assert issued.status_code == 201
        invoice = issued.json()
        server.push_photo(2, "recover-proof", chat_id=987654, caption=f"/receipt {invoice['id']}")
        until(
            lambda: InboxWork.objects.filter(
                event__bot_id=bot, event__update_id=2, status="failed"
            ).exists(),
            timeout=15,
        )
        failed = InboxWork.objects.get(event__bot_id=bot, event__update_id=2)
        root = bot_root + f"/shop/work/{failed.id}"
        before = owner.get(root).json()
        assert before["attempts"] == 1 and Receipt.objects.count() == 0
        server.files["photos/recover-proof.jpg"] = b"controlled-recovered-evidence"
        inputs = recovery(before["revision"])
        accepted = owner.post(root + "/recoveries", inputs, format="json")
        assert accepted.status_code == 201
        until(lambda: Receipt.objects.filter(invoice_id=invoice["id"]).exists(), timeout=15)
        evidence = Receipt.objects.get(invoice_id=invoice["id"])
        assert evidence.request_key == failed.id
        assert bytes(evidence.content) == b"controlled-recovered-evidence"
        failed.refresh_from_db()
        assert failed.status == "done" and failed.attempts == 1
        wallet = f"/api/v1/customer-accounts/{customer}/wallet"
        assert owner.get(wallet).json()["balance_minor"] == "0"
        invoice_root = f"/api/v1/invoices/{invoice['id']}"
        approved = owner.post(
            invoice_root + "/decisions",
            decision(owner.get(invoice_root).json())
            | {
                "receipt_id": str(evidence.id),
            },
            format="json",
        )
        assert approved.status_code == 201
        assert owner.post(root + "/recoveries", inputs, format="json").status_code == 200
        assert owner.get(wallet).json()["balance_minor"] == "1000"
        assert owner.get(wallet + "/entries").json()["count"] == 1
        assert WorkRecovery.objects.filter(work=failed).count() == 1
