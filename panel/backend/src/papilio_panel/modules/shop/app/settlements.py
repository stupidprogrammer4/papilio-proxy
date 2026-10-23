"""Consume committed payment events into scoped encrypted bot replies atomically."""

from uuid import UUID

from django.db import transaction

from papilio_panel.modules.payments.domain import DecisionAction, InvoiceState, PaymentEventOutcome
from papilio_panel.modules.payments.interfaces import InvoiceCapability, PaymentEventCapability
from papilio_panel.shared.errors import Missing

from ..domain import ReplyWrite
from ..interfaces import InvoiceOriginStorage, ShopCustomerQueryCapability, ShopMessageStorage
from .payment_replies import decision_reply


class ShopSettlementNotifications:
    def __init__(
        self,
        events: PaymentEventCapability,
        invoices: InvoiceCapability,
        origins: InvoiceOriginStorage,
        customers: ShopCustomerQueryCapability,
        messages: ShopMessageStorage,
    ) -> None:
        self.events = events
        self.invoices = invoices
        self.origins = origins
        self.customers = customers
        self.messages = messages

    @transaction.atomic
    def notify(self, event_id: UUID, actor_id: int) -> None:
        event = self.events.read(event_id, actor_id)
        if event.processed_at is not None:
            return
        invoice = self.invoices.read(event.invoice_id, actor_id)
        if event.action == DecisionAction.REJECT and invoice.status != InvoiceState.REJECTED:
            self.events.acknowledge(event.id, actor_id, PaymentEventOutcome.SUPERSEDED)
            return
        origin = self.origins.find(invoice.id, actor_id)
        if origin is None:
            self.events.acknowledge(event.id, actor_id, PaymentEventOutcome.NO_CONVERSATION)
            return
        context = self.customers.resolve(origin.event_id)
        if (
            context.customer.id != invoice.customer_id
            or context.customer.owner_id != actor_id
            or context.event.bot.id != origin.bot_id
        ):
            raise Missing("The invoice no longer matches its private conversation owner.")
        response = decision_reply(context, invoice, event.action)
        self.messages.append(
            ReplyWrite(
                origin.event_id,
                origin.bot_id,
                actor_id,
                response,
                invoice_id=invoice.id,
                source_event_id=event.id,
            )
        )
        self.events.acknowledge(event.id, actor_id, PaymentEventOutcome.QUEUED)
