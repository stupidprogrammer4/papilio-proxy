"""Read invoice/evidence targets only within the verified private customer's scope."""

from uuid import UUID

from rest_framework import serializers

from papilio_panel.modules.bots.domain import TelegramReply
from papilio_panel.modules.payments.domain import InvoiceRead, InvoiceState
from papilio_panel.modules.payments.interfaces import InvoiceCapability
from papilio_panel.shared.errors import Conflict, InvalidInput, Missing

from ..domain import InvoiceReplyLookup, ReceiptTarget, ShopCustomerContext
from ..interfaces import ShopMessageStorage
from .payment_replies import invoice_reply


class ShopInvoiceQueries:
    def __init__(self, invoices: InvoiceCapability, messages: ShopMessageStorage) -> None:
        self.invoices = invoices
        self.messages = messages

    def read(self, context: ShopCustomerContext, invoice_id: UUID) -> InvoiceRead:
        invoice = self.invoices.read(invoice_id, context.customer.owner_id)
        if invoice.customer_id != context.customer.id:
            raise Missing("The invoice was not found in this customer chat.")
        return invoice

    def response(self, context: ShopCustomerContext, invoice_id: UUID) -> TelegramReply:
        invoice = self.read(context, invoice_id)
        return invoice_reply(context, invoice)

    def receipt_target(self, context: ShopCustomerContext) -> ReceiptTarget:
        message = context.event.message
        if message is None:
            raise Missing("There is no verified private receipt sender.")
        parts = message.text.split(maxsplit=2)
        reference, note = "", ""
        if parts and parts[0] == "/receipt":
            if len(parts) < 2:
                raise InvalidInput(
                    "Send /receipt INVOICE_ID TRANSFER_REFERENCE or attach the receipt."
                )
            invoice_id = serializers.UUIDField().run_validation(parts[1])
            reference = serializers.CharField(max_length=200, allow_blank=True).run_validation(
                parts[2] if len(parts) == 3 else ""
            )
        elif message.reply_to_message_id is not None:
            invoice_id = self.messages.invoice_for_reply(
                InvoiceReplyLookup(
                    context.event.bot.id,
                    context.customer.owner_id,
                    message.sender_id,
                    message.reply_to_message_id,
                )
            )
            if message.file is None:
                reference = serializers.CharField(max_length=200).run_validation(message.text)
            else:
                note = serializers.CharField(max_length=2000, allow_blank=True).run_validation(
                    message.text
                )
        else:
            raise InvalidInput("Reply to your invoice message or include its ID with /receipt.")
        invoice = self.read(context, invoice_id)
        if invoice.status == InvoiceState.SETTLED:
            raise Conflict("This invoice is already settled; no new evidence is needed.")
        if not reference and message.file is None:
            raise InvalidInput("Supply a transfer reference or attach your receipt.")
        return ReceiptTarget(invoice.id, reference, note, invoice.settings.receipt_max_bytes)
