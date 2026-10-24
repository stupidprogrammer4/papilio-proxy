"""Native receipt retry deadlines, current policies and final failure effects."""

from datetime import timedelta

import pytest
from django.utils import timezone
from telegram_server import TelegramServer
from test_nodes import owner_client
from test_shop_payments import incoming_text, payment_bot, process

from papilio_panel.modules.bots.models import TelegramInbox
from papilio_panel.modules.bots.providers import polling
from papilio_panel.modules.payments.models import Invoice, Receipt
from papilio_panel.modules.shop.domain import ReceiptDownloadFailure
from papilio_panel.modules.shop.models import InboxWork, OutgoingMessage
from papilio_panel.modules.shop.providers import execution
from papilio_panel.shared.errors import Conflict

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize(
    "status,max_attempts,retries", [(0, 2, True), (503, 2, True), (503, 1, False), (404, 5, False)]
)
def test_receipt_retry_keeps_due_time_budget_and_unprocessed_event(
    status: int, max_attempts: int, retries: bool
) -> None:
    server = TelegramServer()
    with server.running() as address:
        owner = owner_client()
        bot, customer = payment_bot(owner, server, address)
        process(incoming_text(server, bot, 2, "/topup 1000"))
        invoice = Invoice.objects.get()
        root = f"/api/v1/bots/{bot}/shop"
        current = owner.get(root).json()
        assert (
            owner.put(
                root,
                current["definition"]
                | {
                    "expected_revision": current["revision"],
                    "retry_seconds": 17,
                    "max_attempts": max_attempts,
                },
                format="json",
            ).status_code
            == 200
        )
        server.files["photos/proof.jpg"] = b"private-evidence"
        server.file_statuses = [status]
        server.push_photo(3, "proof", chat_id=987654, caption=f"/receipt {invoice.id} REFERENCE")
        polling.poll(bot)
        work = InboxWork.objects.create(event=TelegramInbox.objects.get(bot_id=bot, update_id=3))
        claim = execution.begin(work.id)
        assert claim is not None
        with pytest.raises(ReceiptDownloadFailure) as failure:
            execution.prepare(claim)
        outcome = execution.retry_receipt(claim, failure.value)
        work.refresh_from_db()
        assert work.attempts == 1 and work.lease_token is None
        assert Receipt.objects.count() == 0
        assert (
            owner.get(f"/api/v1/customer-accounts/{customer}/wallet").json()["balance_minor"] == "0"
        )
        if not retries:
            assert outcome.retry_after_seconds is None and work.status == "failed"
            assert work.retry_at is None and work.event.processed_at is not None
            assert OutgoingMessage.objects.filter(event=work.event).count() == 1
            assert execution.begin(work.id) is None
            return
        assert outcome.retry_after_seconds == 17
        assert work.status == "queued" and work.retry_at is not None
        assert work.retry_at > timezone.now() + timedelta(seconds=15)
        assert work.event.processed_at is None
        assert not OutgoingMessage.objects.filter(event=work.event).exists()
        assert execution.begin(work.id) is None
        with pytest.raises(Conflict):
            execution.retry_receipt(claim, failure.value)
        # Move only this test-owned deadline; no wall-clock sleep or live data mutation.
        InboxWork.objects.filter(pk=work.id).update(retry_at=timezone.now() - timedelta(seconds=1))
        second = execution.begin(work.id)
        assert second is not None and second.attempts == 2
        prepared = execution.prepare(second)
        execution.process(second, prepared)
        work.refresh_from_db()
        assert work.status == "done" and work.attempts == 2
        assert work.error_code is None and work.retry_at is None
        assert Receipt.objects.get(invoice=invoice).request_key == work.id
        assert execution.begin(work.id) is None
        assert server.file_calls == ["photos/proof.jpg", "photos/proof.jpg"]


def test_rate_limit_delay_and_pause_preserve_receipt_without_acknowledging_it() -> None:
    server = TelegramServer()
    with server.running() as address:
        owner = owner_client()
        bot, _ = payment_bot(owner, server, address)
        process(incoming_text(server, bot, 2, "/topup 1000"))
        invoice = Invoice.objects.get()
        server.replies["getFile"] = (429, {"ok": False, "parameters": {"retry_after": 89}})
        server.push_photo(3, "proof", chat_id=987654, caption=f"/receipt {invoice.id}")
        polling.poll(bot)
        work = InboxWork.objects.create(event=TelegramInbox.objects.get(bot_id=bot, update_id=3))
        claim = execution.begin(work.id)
        assert claim is not None
        with pytest.raises(ReceiptDownloadFailure) as failure:
            execution.prepare(claim)
        outcome = execution.retry_receipt(claim, failure.value)
        assert outcome.retry_after_seconds == 89
        assert server.file_calls == [] and Receipt.objects.count() == 0
        InboxWork.objects.filter(pk=work.id).update(retry_at=timezone.now() - timedelta(seconds=1))
        claimed = execution.begin(work.id)
        assert claimed is not None
        root = f"/api/v1/bots/{bot}/shop"
        current = owner.get(root).json()
        assert (
            owner.put(
                root,
                current["definition"]
                | {
                    "expected_revision": current["revision"],
                    "enabled": False,
                },
                format="json",
            ).status_code
            == 200
        )
        assert execution.retry_receipt(claimed, failure.value).retry_after_seconds is None
        work.refresh_from_db()
        assert work.status == "queued" and work.retry_at is None
        assert work.event.processed_at is None
        assert not OutgoingMessage.objects.filter(event=work.event).exists()
