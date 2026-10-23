"""Issue frozen invoices and submit private evidence through shared payment owners."""

from uuid import UUID

from django.db import transaction

from papilio_panel.modules.bots.domain import TelegramReply
from papilio_panel.modules.payments.domain import InvoiceIssue, ReceiptSubmit
from papilio_panel.modules.payments.interfaces import InvoiceCapability, ReceiptCapability
from papilio_panel.shared.errors import Missing

from ..domain import (
    InvoiceOrigin,
    PreparedReceipt,
    ReplyWrite,
    ShopCustomerContext,
)
from ..interfaces import InvoiceOriginStorage, ShopInvoiceQueryCapability, ShopMessageStorage
from .payment_replies import invoice_reply, receipt_replies
from .presentation import menu


class ShopFunding:
    def __init__(
        self,
        invoices: InvoiceCapability,
        receipts: ReceiptCapability,
        queries: ShopInvoiceQueryCapability,
        origins: InvoiceOriginStorage,
        messages: ShopMessageStorage,
    ) -> None:
        self.invoices = invoices
        self.receipts = receipts
        self.queries = queries
        self.origins = origins
        self.messages = messages

    @transaction.atomic
    def issue(self, context: ShopCustomerContext, work_id: UUID, amount: int) -> None:
        invoice = self.invoices.issue(
            InvoiceIssue(context.customer.owner_id, work_id, context.customer.id, amount)
        ).invoice
        self.origins.create(
            InvoiceOrigin(
                invoice.id,
                context.event.id,
                context.event.bot.id,
                context.customer.owner_id,
                context.customer.id,
            )
        )
        self.messages.append(
            ReplyWrite(
                context.event.id,
                context.event.bot.id,
                context.customer.owner_id,
                invoice_reply(context, invoice),
                invoice_id=invoice.id,
            )
        )
        if invoice.settings.instructions:
            self.messages.append(
                ReplyWrite(
                    context.event.id,
                    context.event.bot.id,
                    context.customer.owner_id,
                    TelegramReply(invoice.settings.instructions, menu(context.settings.definition)),
                    invoice_id=invoice.id,
                )
            )

    @transaction.atomic
    def submit(self, context: ShopCustomerContext, work_id: UUID, receipt: PreparedReceipt) -> None:
        if receipt.event_id != context.event.id:
            raise Missing("This receipt belongs to a different private incoming event.")
        invoice = self.queries.read(context, receipt.invoice_id)
        self.receipts.submit(
            ReceiptSubmit(
                context.customer.owner_id,
                invoice.id,
                work_id,
                receipt.reference,
                receipt.note,
                receipt.file,
            )
        )
        if self.origins.find(invoice.id, context.customer.owner_id) is None:
            self.origins.create(
                InvoiceOrigin(
                    invoice.id,
                    context.event.id,
                    context.event.bot.id,
                    context.customer.owner_id,
                    context.customer.id,
                )
            )
        responses = receipt_replies(context, invoice, receipt.reference)
        self.messages.append(
            ReplyWrite(
                context.event.id,
                context.event.bot.id,
                context.customer.owner_id,
                responses.acknowledgement,
                invoice_id=invoice.id,
            )
        )
        self.messages.append(
            ReplyWrite(
                context.event.id,
                context.event.bot.id,
                context.customer.owner_id,
                responses.review_notice,
                administrator=True,
                invoice_id=invoice.id,
            )
        )
