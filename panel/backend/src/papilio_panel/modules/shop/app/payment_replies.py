"""Pure customer invoice, evidence and decision replies without private audit notes."""

from urllib.parse import urlencode

from papilio_panel.modules.bots.domain import TelegramButton, TelegramReply
from papilio_panel.modules.payments.domain import DecisionAction, InvoiceRead, ReceiptRead

from ..domain import ReceiptReplies, ShopCustomerContext, ShopTextContext
from .presentation import menu, render, reply


def invoice_reply(context: ShopCustomerContext, invoice: InvoiceRead) -> TelegramReply:
    settings = context.settings.definition
    text = render(
        settings,
        "invoice",
        ShopTextContext(
            invoice_id=str(invoice.id),
            amount=str(invoice.amount_due_minor),
            name=invoice.settings.recipient,
            destination=invoice.settings.destination,
            instructions=invoice.settings.instructions,
            status=invoice.status.value,
        ),
    )
    return TelegramReply(
        text, (TelegramButton(str(invoice.id), f"invoice:{invoice.id.hex}"),) + menu(settings)
    )


def receipt_replies(
    context: ShopCustomerContext, invoice: InvoiceRead, receipt: ReceiptRead
) -> ReceiptReplies:
    settings = context.settings.definition
    acknowledgement = reply(settings, "receipt", ShopTextContext(invoice_id=str(invoice.id)))
    url = (
        settings.public_origin.rstrip("/")
        + "/invoices?"
        + urlencode({"invoice_id": str(invoice.id), "receipt_id": str(receipt.id)})
    )
    text = render(
        settings,
        "admin_receipt",
        ShopTextContext(
            invoice_id=str(invoice.id),
            amount=str(invoice.amount_due_minor),
            reference=receipt.reference,
            url=url,
        ),
    )
    review_notice = TelegramReply(text, (TelegramButton(str(invoice.id), url=url),))
    return ReceiptReplies(acknowledgement, review_notice)


def decision_reply(
    context: ShopCustomerContext, invoice: InvoiceRead, action: DecisionAction
) -> TelegramReply:
    if action == DecisionAction.REJECT:
        return invoice_reply(context, invoice)
    settings = context.settings.definition
    text = render(
        settings,
        "paid",
        ShopTextContext(
            invoice_id=str(invoice.id),
            amount=str(invoice.base_amount_minor),
            status=invoice.status.value,
        ),
    )
    return TelegramReply(
        text, (TelegramButton(str(invoice.id), f"invoice:{invoice.id.hex}"),) + menu(settings)
    )
