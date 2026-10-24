"""Process one durable verified conversation event with its replies atomically."""

from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from papilio_panel.modules.bots.interfaces import BotConversationCapability
from papilio_panel.shared.errors import Conflict
from papilio_panel.shared.serializers import MoneyAmountField

from ..domain import (
    PreparedReceipt,
    ReceiptDownloadFailure,
    ReplyWrite,
    ShopCustomerContext,
    ShopTextContext,
    WorkClaim,
    WorkRetryOutcome,
    WorkState,
)
from ..interfaces import (
    ShopControlCapability,
    ShopCustomerCapability,
    ShopDeliverySchedule,
    ShopFundingCapability,
    ShopMenuCapability,
    ShopMessageStorage,
    ShopPurchaseCapability,
    ShopReceiptPreparationCapability,
    ShopWorkStorage,
)
from .presentation import reply
from .receipt_policy import exhausted, retry_delay


def is_pairing_command(text: str) -> bool:
    parts = text.split(maxsplit=1)
    return (
        len(parts) == 2
        and parts[0].partition("@")[0] == "/start"
        and parts[1] == "[pairing redacted]"
    )


class ShopExecution:
    def __init__(
        self,
        storage: ShopWorkStorage,
        messages: ShopMessageStorage,
        events: BotConversationCapability,
        control: ShopControlCapability,
        customers: ShopCustomerCapability,
        menus: ShopMenuCapability,
        schedule: ShopDeliverySchedule,
        purchases: ShopPurchaseCapability,
        funding: ShopFundingCapability,
        receipt_preparation: ShopReceiptPreparationCapability,
    ) -> None:
        self.storage = storage
        self.messages = messages
        self.events = events
        self.control = control
        self.customers = customers
        self.menus = menus
        self.schedule = schedule
        self.purchases = purchases
        self.funding = funding
        self.receipt_preparation = receipt_preparation

    def begin(self, work_id: UUID) -> WorkClaim | None:
        row = self.storage.read(work_id)
        if row.status in {WorkState.DONE, WorkState.FAILED} or not self.schedule.enabled():
            return None
        event = self.events.event(row.event_id)
        settings = self.control.read(event.bot.id, event.bot.owner_id)
        if (
            not settings.definition.enabled
            or not event.bot.schedule.enabled
            or not event.bot.verified
        ):
            return None
        lease = self.storage.claim(
            row.id,
            max(settings.definition.lease_seconds, 3 * event.bot.runtime.http_timeout_seconds + 60),
        )
        if lease is None:
            return None
        claim = WorkClaim(row.id, lease.token, event, settings, lease.attempts)
        if exhausted(row.error_code, claim.attempts, settings.definition):
            self.fail(
                claim, "receipt_attempt_limit", "The receipt preparation attempt limit was reached."
            )
            return None
        return claim

    def prepare(self, claim: WorkClaim) -> PreparedReceipt | None:
        result = self.receipt_preparation.prepare(claim.event.id)
        return result

    @transaction.atomic
    def retry_receipt(self, claim: WorkClaim, error: ReceiptDownloadFailure) -> WorkRetryOutcome:
        event = self.events.event(claim.event.id)
        policy = self.control.read(event.bot.id, event.bot.owner_id).definition
        if not policy.enabled or not event.bot.schedule.enabled or not self.schedule.enabled():
            self.storage.release(claim)
            return WorkRetryOutcome()
        delay = retry_delay(error, claim.attempts, policy)
        if delay is None:
            self.fail(claim, error.transport_code, str(error))
            return WorkRetryOutcome()
        self.storage.defer(claim, timezone.now() + timedelta(seconds=delay), error.transport_code)
        return WorkRetryOutcome(delay)

    @transaction.atomic
    def process(self, claim: WorkClaim, receipt: PreparedReceipt | None = None) -> None:
        event = self.events.event(claim.event.id)
        current = self.control.read(event.bot.id, event.bot.owner_id)
        if (
            not current.definition.enabled
            or not event.bot.schedule.enabled
            or not self.schedule.enabled()
        ):
            raise Conflict("The bot shop was paused before the conversation committed.")
        message = event.message
        if message is not None and not is_pairing_command(message.text):
            customer = self.customers.register(event.id)
            self.respond(customer, claim.id, receipt)
        self.storage.complete(claim)
        self.events.processed(event.id, event.bot.id, event.bot.owner_id)

    def respond(
        self, context: ShopCustomerContext, work_id: UUID, receipt: PreparedReceipt | None
    ) -> None:
        if receipt is not None:
            self.funding.submit(context, work_id, receipt)
            return
        message = context.event.message
        command = (message.callback_data or message.text).strip() if message is not None else ""
        parts = command.split(maxsplit=1)
        if parts and parts[0] == "/topup":
            amount = MoneyAmountField(min_value=1).run_validation(
                parts[1] if len(parts) == 2 else ""
            )
            self.funding.issue(context, work_id, amount)
            return
        action, _, argument = command.partition(":")
        if action == "offer":
            product_id = serializers.UUIDField().run_validation(argument)
            rendered = self.purchases.select(context, work_id, product_id)
        elif action == "buy":
            confirmation_id = serializers.UUIDField().run_validation(argument)
            rendered = self.purchases.confirm(context, confirmation_id)
        else:
            rendered = self.menus.response(context)
        self.messages.append(
            ReplyWrite(context.event.id, context.event.bot.id, context.customer.owner_id, rendered)
        )

    @transaction.atomic
    def fail(self, claim: WorkClaim, code: str, reason: str) -> None:
        event = self.events.event(claim.event.id)
        settings = self.control.read(event.bot.id, event.bot.owner_id)
        if (
            not settings.definition.enabled
            or not event.bot.schedule.enabled
            or not self.schedule.enabled()
        ):
            self.storage.release(claim)
            return
        if (
            event.message is not None
            and settings.definition.enabled
            and event.bot.schedule.enabled
            and self.schedule.enabled()
        ):
            rendered = reply(settings.definition, "error", ShopTextContext(reason=reason))
            self.messages.append(ReplyWrite(event.id, event.bot.id, event.bot.owner_id, rendered))
        self.storage.complete(claim, code)
        self.events.processed(event.id, event.bot.id, event.bot.owner_id)
