"""Pure issued-term, evidence and decision policies."""

from pathlib import PurePosixPath

from papilio_panel.modules.wallets.domain import EntryKind, JournalInput, WalletPost
from papilio_panel.shared.errors import Conflict, InvalidInput
from papilio_panel.shared.money import MAX_MONEY_MINOR

from ..domain import (
    MAX_RECEIPT_BYTES,
    DecisionAction,
    DecisionInput,
    InvoiceIssue,
    InvoiceRead,
    PaymentDefinition,
    ReceiptSubmit,
)


def payment_definition(values: PaymentDefinition) -> None:
    if not values.recipient.strip() or len(values.recipient) > 80:
        raise InvalidInput("Enter the payment recipient name up to 80 characters.")
    if not values.destination.strip() or len(values.destination) > 120:
        raise InvalidInput(
            "Enter the receiving account or payment destination up to 120 characters."
        )
    if len(values.instructions) > 2000 or type(values.enabled) is not bool:
        raise InvalidInput("Enter valid instructions and an explicit availability choice.")
    if (
        type(values.receipt_max_bytes) is not int
        or not 1 <= values.receipt_max_bytes <= MAX_RECEIPT_BYTES
    ):
        raise InvalidInput(
            "Choose a positive receipt byte limit below PostgreSQL's 1 GiB field limit."
        )


def revision(value: int) -> None:
    if type(value) is not int or not 1 <= value < MAX_MONEY_MINOR:
        raise InvalidInput("Choose a positive configuration revision within signed BIGINT.")


def invoice_amount(value: int) -> None:
    if type(value) is not int or not 1 <= value <= MAX_MONEY_MINOR:
        raise InvalidInput("Choose a positive integer invoice amount within signed BIGINT.")


def matching_invoice(invoice: InvoiceRead, values: InvoiceIssue) -> None:
    if (
        invoice.customer_id != values.customer_id
        or invoice.base_amount_minor != values.base_amount_minor
    ):
        raise Conflict("This invoice request key belongs to different terms.")


def receipt_input(values: ReceiptSubmit, limit: int) -> None:
    if not values.reference.strip() and values.file is None:
        raise InvalidInput("Supply a payment reference or receipt file.")
    if len(values.reference) > 200 or len(values.note) > 2000:
        raise InvalidInput("The receipt reference or note exceeds its supported length.")
    evidence = values.file
    if evidence is not None:
        if (
            not evidence.filename
            or PurePosixPath(evidence.filename).name != evidence.filename
            or "\\" in evidence.filename
            or len(evidence.filename) > 255
        ):
            raise InvalidInput("Choose a receipt filename without directory components.")
        if not evidence.data or len(evidence.data) > limit or len(evidence.media_type) > 100:
            raise InvalidInput(
                "The receipt file is empty or exceeds the invoice's recorded byte limit."
            )


def decision_input(values: DecisionInput) -> None:
    revision(values.expected_revision)
    if values.action not in (DecisionAction.APPROVE, DecisionAction.REJECT):
        raise InvalidInput("Choose approve or reject.")
    if (
        not values.reason.strip()
        or values.reason != values.reason.strip()
        or len(values.reason) > 500
    ):
        raise InvalidInput(
            "Record the decision reason up to 500 characters without surrounding whitespace."
        )


def invoice_credit(invoice: InvoiceRead, actor_id: int) -> WalletPost:
    return WalletPost(
        actor_id,
        invoice.customer_id,
        JournalInput(
            invoice.id,
            EntryKind.CREDIT,
            invoice.base_amount_minor,
            f"Manual payment invoice {invoice.id}",
        ),
    )
