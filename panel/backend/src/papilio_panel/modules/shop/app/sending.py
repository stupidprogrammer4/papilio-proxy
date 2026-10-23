"""Revalidate destinations and persist native send outcomes without financial replay."""

from datetime import timedelta
from uuid import UUID

from django.utils import timezone

from papilio_panel.modules.bots.domain import BotReplyRequest, TelegramSendResult
from papilio_panel.modules.bots.interfaces import BotConversationCapability
from papilio_panel.shared.errors import Missing

from ..domain import MessageClaim, MessageState, ShopSendOutcome
from ..interfaces import ShopControlCapability, ShopDeliverySchedule, ShopMessageStorage
from .send_policy import disposition


class ShopSending:
    def __init__(
        self,
        storage: ShopMessageStorage,
        events: BotConversationCapability,
        control: ShopControlCapability,
        schedule: ShopDeliverySchedule,
    ) -> None:
        self.storage = storage
        self.events = events
        self.control = control
        self.schedule = schedule

    def begin(self, message_id: UUID) -> MessageClaim | None:
        row = self.storage.reference(message_id)
        if (
            row.status in {MessageState.SENT, MessageState.AMBIGUOUS, MessageState.FAILED}
            or not self.schedule.enabled()
        ):
            return None
        event = self.events.event(row.event_id)
        if event.bot.id != row.bot_id or event.bot.owner_id != row.owner_id:
            raise Missing("The outgoing message does not belong to this bot event.")
        settings = self.control.read(row.bot_id, row.owner_id)
        definition = settings.definition
        if (
            not definition.enabled
            or not definition.delivery_enabled
            or not event.bot.schedule.enabled
            or not event.bot.verified
        ):
            return None
        if row.status == MessageState.SENDING:
            status = (
                MessageState.RETRY
                if definition.ambiguous_delivery == "retry"
                else MessageState.AMBIGUOUS
            )
            self.storage.expire(
                row.id,
                status,
                timezone.now() + timedelta(seconds=definition.retry_seconds)
                if status == MessageState.RETRY
                else None,
            )
            return None
        if row.attempts >= definition.max_attempts:
            self.storage.reject(row.id, "attempt_limit_reached")
            return None
        if row.administrator and event.bot.admin_chat_id is None:
            return None
        claim = self.storage.claim(
            row.id,
            settings,
            max(definition.lease_seconds, 2 * event.bot.runtime.http_timeout_seconds + 30),
        )
        return claim

    def send(self, claim: MessageClaim) -> ShopSendOutcome:
        if not self.storage.active(claim):
            return ShopSendOutcome()
        current = self.control.read(claim.values.bot_id, claim.values.owner_id)
        event = self.events.event(claim.values.event_id)
        if (
            not current.definition.enabled
            or not current.definition.delivery_enabled
            or not self.schedule.enabled()
            or not event.bot.schedule.enabled
        ):
            self.storage.release(claim)
            return ShopSendOutcome()
        result = self.events.reply(
            BotReplyRequest(
                claim.values.event_id,
                claim.values.bot_id,
                claim.values.owner_id,
                claim.values.reply,
                claim.values.administrator,
            )
        )
        outcome = self.finish(claim, result)
        return outcome

    def fail(self, claim: MessageClaim, error_code: str) -> ShopSendOutcome:
        outcome = self.finish(claim, TelegramSendResult(error_code=error_code))
        return outcome

    def finish(self, claim: MessageClaim, result: TelegramSendResult) -> ShopSendOutcome:
        decision = disposition(result, claim.attempts, claim.settings.definition)
        delay = decision.retry_after_seconds
        self.storage.complete(
            claim,
            result,
            decision.status,
            timezone.now() + timedelta(seconds=delay) if delay is not None else None,
        )
        return ShopSendOutcome(delay)
