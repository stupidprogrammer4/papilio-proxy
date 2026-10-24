"""Owner-scoped HTTP recovery preserves identity, audit and financial effects."""

from uuid import uuid4

import pytest
from rest_framework.test import APIClient
from telegram_server import TelegramServer
from test_bots import bot_input
from test_nodes import owner_client
from test_shop_customers import configured_event
from test_shop_payments import incoming_text
from test_shop_purchases import execute

from papilio_panel.config.celery import app
from papilio_panel.modules.shop.domain import ShopTaskName
from papilio_panel.modules.shop.models import InboxWork, OutgoingMessage
from papilio_panel.modules.shop.providers import sending
from papilio_panel.modules.wallets.models import JournalEntry

pytestmark = pytest.mark.django_db(transaction=True)


def failed_work(owner: APIClient, server: TelegramServer, address: str) -> InboxWork:
    event_id = configured_event(owner, server, address)
    welcome = InboxWork.objects.create(event_id=event_id)
    execute(welcome)
    bot_id = welcome.event.bot.id
    work = incoming_text(server, bot_id, 2, "/topup not-an-amount")
    app.tasks[ShopTaskName.PROCESS.value].apply(kwargs={"work_id": str(work.id)}, throw=True)
    work.refresh_from_db()
    assert work.status == "failed"
    return work


def recovery(revision: str, action: str = "retry") -> dict:
    return {
        "request_key": str(uuid4()),
        "expected_revision": revision,
        "action": action,
        "note": "Private operator recovery note",
    }


def test_work_recovery_preserves_identity_and_rejects_replay_changes() -> None:
    server = TelegramServer()
    with server.running() as address:
        owner = owner_client()
        work = failed_work(owner, server, address)
        root = f"/api/v1/bots/{work.event.bot.id}/shop/work"
        record = owner.get(f"{root}/{work.id}")
        assert record.status_code == 200
        assert set(record.json()["actions"]) == {"retry", "cancel"}
        values = recovery(record.json()["revision"])
        accepted = owner.post(f"{root}/{work.id}/recoveries", values, format="json")
        assert accepted.status_code == 201
        result = accepted.json()
        assert result["work"]["id"] == str(work.id)
        assert result["work"]["status"] == "queued" and result["work"]["attempts"] == 0
        assert result["recovery"]["previous_status"] == "failed"
        assert result["recovery"]["previous_attempts"] == 1
        replay = owner.post(f"{root}/{work.id}/recoveries", values, format="json")
        assert replay.status_code == 200 and replay.json()["recovery"] == result["recovery"]
        assert (
            owner.post(
                f"{root}/{work.id}/recoveries",
                values
                | {
                    "note": "Different replay body",
                },
                format="json",
            ).status_code
            == 409
        )
        assert (
            owner.post(
                f"{root}/{work.id}/recoveries",
                recovery(values["expected_revision"], "cancel"),
                format="json",
            ).status_code
            == 409
        )
        audit = owner.get(f"{root}/{work.id}/recoveries?page=1&page_size=1").json()
        assert audit["count"] == 1 and audit["items"][0] == result["recovery"]
        work.refresh_from_db()
        assert work.status == "queued" and work.attempts == 0
        assert JournalEntry.objects.count() == 0


def test_recovery_checks_both_bot_parent_and_current_owner() -> None:
    server = TelegramServer()
    with server.running() as address:
        owner = owner_client()
        work = failed_work(owner, server, address)
        root = f"/api/v1/bots/{work.event.bot.id}/shop/work"
        other_bot_response = owner.post(
            "/api/v1/bots",
            bot_input(
                "Other recovery bot",
                "987654321:placeholder-not-a-real-second-token",
            ),
            format="json",
        )
        assert other_bot_response.status_code == 202
        other_bot = other_bot_response.json()
        record = owner.get(f"{root}/{work.id}")
        assert record.status_code == 200
        values = recovery(record.json()["revision"])
        foreign = owner_client("foreign-recovery-owner")
        staff = owner_client("recovery-staff", superuser=False)
        assert foreign.get(root).status_code == 404
        assert (
            foreign.post(f"{root}/{work.id}/recoveries", values, format="json").status_code == 404
        )
        assert staff.get(root).status_code == 401
        wrong_parent = f"/api/v1/bots/{other_bot['id']}/shop/work/{work.id}"
        assert owner.get(wrong_parent).status_code == 404
        assert owner.post(wrong_parent + "/recoveries", values, format="json").status_code == 404
        listed = owner.get(root + "?page=1&page_size=1").json()
        assert listed["count"] == 2 and len(listed["items"]) == 1
        assert owner.get(root + f"?q={work.id}").json()["count"] == 1
        assert owner.get(f"/api/v1/bots/{other_bot['id']}/shop/work").json()["count"] == 0
        assert owner.get(root + "?page_size=0").status_code == 400
        work.refresh_from_db()
        assert work.status == "failed"


def test_uncertain_message_retry_uses_stored_reply_without_replaying_business() -> None:
    server = TelegramServer()
    with server.running() as address:
        owner = owner_client()
        work = failed_work(owner, server, address)
        message = OutgoingMessage.objects.get(event=work.event)
        original = bytes(message.payload_ciphertext)
        claim = sending.begin(message.id)
        assert claim is not None
        server.replies["sendMessage"] = (500, {"ok": False})
        sending.send(claim)
        message.refresh_from_db()
        assert message.status == "ambiguous"
        root = f"/api/v1/bots/{message.bot_id}/shop/messages/{message.id}"
        record = owner.get(root)
        assert record.status_code == 200
        assert "payload_ciphertext" not in record.json() and "text" not in record.json()
        values = recovery(record.json()["revision"])
        accepted = owner.post(root + "/recoveries", values, format="json")
        assert accepted.status_code == 201
        assert accepted.json()["message"]["status"] == "queued"
        assert accepted.json()["recovery"]["previous_status"] == "ambiguous"
        del server.replies["sendMessage"]
        retried = sending.begin(message.id)
        assert retried is not None
        sending.send(retried)
        message.refresh_from_db()
        assert message.status == "sent" and message.attempts == 1
        assert bytes(message.payload_ciphertext) == original
        assert owner.post(root + "/recoveries", values, format="json").status_code == 200
        fresh = owner.get(root).json()
        assert fresh["actions"] == []
        assert (
            owner.post(root + "/recoveries", recovery(fresh["revision"]), format="json").status_code
            == 409
        )
        assert JournalEntry.objects.count() == 0
        assert all("Private operator" not in item["text"] for _, item in server.messages)
