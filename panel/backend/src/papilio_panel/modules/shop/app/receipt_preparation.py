"""Fetch a scoped Telegram receipt in the I/O worker before opening the DB transaction."""

from papilio_panel.modules.bots.interfaces import BotConversationCapability
from papilio_panel.modules.payments.domain import ReceiptContent

from ..domain import PreparedReceipt, ReceiptDownloadFailure
from ..interfaces import ShopCustomerQueryCapability, ShopInvoiceQueryCapability


class ShopReceiptPreparation:
    def __init__(
        self,
        events: BotConversationCapability,
        customers: ShopCustomerQueryCapability,
        invoices: ShopInvoiceQueryCapability,
    ) -> None:
        self.events = events
        self.customers = customers
        self.invoices = invoices

    def prepare(self, event_id: int) -> PreparedReceipt | None:
        event = self.events.event(event_id)
        message = event.message
        if message is None:
            return None
        command = message.text.split(maxsplit=1)
        if (
            message.file is None
            and message.reply_to_message_id is None
            and (not command or command[0] != "/receipt")
        ):
            return None
        context = self.customers.resolve(event.id)
        target = self.invoices.receipt_target(context)
        content = None
        if message.file is not None:
            downloaded = self.events.file(event.id, target.max_bytes)
            if downloaded.content is None:
                raise ReceiptDownloadFailure(
                    downloaded.error_code or "unknown_error", downloaded.retry_after_seconds
                )
            content = ReceiptContent(
                downloaded.content.filename, downloaded.content.media_type, downloaded.content.data
            )
        return PreparedReceipt(event.id, target.invoice_id, target.reference, target.note, content)
