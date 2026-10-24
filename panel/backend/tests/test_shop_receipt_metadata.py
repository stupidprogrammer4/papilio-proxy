"""Invalid getFile metadata requests are terminal rather than transport retries."""

import pytest
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


@pytest.mark.parametrize("status", [400, 403])
def test_invalid_receipt_file_metadata_does_not_enter_an_automatic_retry(status: int) -> None:
    server = TelegramServer()
    with server.running() as address:
        owner = owner_client()
        bot, _ = payment_bot(owner, server, address)
        process(incoming_text(server, bot, 2, "/topup 1000"))
        invoice = Invoice.objects.get()
        server.replies["getFile"] = (status, {"ok": False, "error_code": status})
        server.push_photo(3, "invalid-file", chat_id=987654, caption=f"/receipt {invoice.id}")
        polling.poll(bot)
        work = InboxWork.objects.create(event=TelegramInbox.objects.get(bot_id=bot, update_id=3))
        claim = execution.begin(work.id)
        assert claim is not None
        with pytest.raises(ReceiptDownloadFailure) as failure:
            execution.prepare(claim)
        assert execution.retry_receipt(claim, failure.value).retry_after_seconds is None
        work.refresh_from_db()
        assert work.status == "failed" and work.error_code == "file_unavailable"
        assert Receipt.objects.count() == 0 and server.file_calls == []
