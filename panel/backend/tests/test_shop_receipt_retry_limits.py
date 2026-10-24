"""A lowered operator retry budget stops a fresh HTTP attempt."""

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
from papilio_panel.modules.shop.models import InboxWork
from papilio_panel.modules.shop.providers import execution

pytestmark = pytest.mark.django_db(transaction=True)


def test_lowered_retry_budget_stops_the_next_download() -> None:
    server = TelegramServer()
    with server.running() as address:
        owner = owner_client()
        bot, _ = payment_bot(owner, server, address)
        process(incoming_text(server, bot, 2, "/topup 1000"))
        invoice = Invoice.objects.get()
        server.files["photos/proof.jpg"] = b"private-evidence"
        server.file_statuses = [503]
        server.push_photo(3, "proof", chat_id=987654, caption=f"/receipt {invoice.id}")
        polling.poll(bot)
        work = InboxWork.objects.create(event=TelegramInbox.objects.get(bot_id=bot, update_id=3))
        claim = execution.begin(work.id)
        assert claim is not None
        with pytest.raises(ReceiptDownloadFailure) as failure:
            execution.prepare(claim)
        assert execution.retry_receipt(claim, failure.value).retry_after_seconds == 30
        root = f"/api/v1/bots/{bot}/shop"
        current = owner.get(root).json()
        changed = owner.put(
            root,
            current["definition"]
            | {
                "expected_revision": current["revision"],
                "max_attempts": 1,
            },
            format="json",
        )
        assert changed.status_code == 200
        InboxWork.objects.filter(pk=work.id).update(retry_at=timezone.now() - timedelta(seconds=1))
        assert execution.begin(work.id) is None
        work.refresh_from_db()
        assert work.status == "failed" and work.event.processed_at is not None
        assert Receipt.objects.count() == 0
        assert server.file_calls == ["photos/proof.jpg"]
