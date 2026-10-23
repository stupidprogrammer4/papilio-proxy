"""Native transaction coordinates audited manual decisions and one wallet credit."""

from django.db import transaction

from papilio_panel.modules.wallets.interfaces import WalletCapability
from papilio_panel.shared.errors import Conflict

from ..domain import (
    DecisionAction,
    DecisionInput,
    DecisionResult,
    InvoiceState,
    InvoiceTransition,
)
from ..interfaces import InvoiceCapability, InvoiceStorage, PaymentEventStorage, ReceiptCapability
from .validation import decision_input, invoice_credit


class ManualPaymentDecisions:
    def __init__(
        self,
        storage: InvoiceStorage,
        invoices: InvoiceCapability,
        receipts: ReceiptCapability,
        wallets: WalletCapability,
        events: PaymentEventStorage,
    ) -> None:
        self.storage = storage
        self.invoices = invoices
        self.receipts = receipts
        self.wallets = wallets
        self.events = events

    @transaction.atomic
    def decide(self, values: DecisionInput) -> DecisionResult:
        invoice = self.invoices.read(values.invoice_id, values.actor_id)
        decision_input(values)
        if values.receipt_id is not None:
            self.receipts.read(values.receipt_id, values.invoice_id, values.actor_id)
        reserved = self.storage.reserve_decision(values)
        if reserved.original != values:
            raise Conflict("This decision request key belongs to different approval details.")
        if reserved.created:
            target = (
                InvoiceState.SETTLED
                if values.action == DecisionAction.APPROVE
                else InvoiceState.REJECTED
            )
            self.storage.transition(
                InvoiceTransition(values.actor_id, invoice.id, values.expected_revision, target)
            )
            if values.action == DecisionAction.APPROVE:
                credit = self.wallets.post(invoice_credit(invoice, values.actor_id))
                self.storage.complete_decision(
                    reserved.decision.id, values.actor_id, credit.entry.id
                )
            self.events.append(reserved.decision.id)
        current = self.invoices.read(invoice.id, values.actor_id)
        result = self.storage.read_decision(reserved.decision.id, invoice.id, values.actor_id)
        return DecisionResult(current, result, reserved.created)
