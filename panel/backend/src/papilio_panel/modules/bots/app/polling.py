"""Revalidate operators, verify bot identity and commit incoming updates durably."""

from uuid import UUID

from django.utils import timezone

from papilio_panel.modules.identity.interfaces import AdminAccessCapability

from ..domain import BotCompletion, BotPollClaim, BotPollResult, TelegramIdentity
from ..interfaces import BotStorage, TelegramGateway
from .pairing import paired_chat, retained_updates


class BotPolling:
    def __init__(
        self, storage: BotStorage, access: AdminAccessCapability, telegram: TelegramGateway
    ) -> None:
        self.storage = storage
        self.access = access
        self.telegram = telegram

    def identify(self, claim: BotPollClaim) -> TelegramIdentity | None:
        if claim.bot.verified and claim.bot.telegram_id is not None and claim.bot.username:
            return TelegramIdentity(id=claim.bot.telegram_id, username=claim.bot.username)
        inspected = self.telegram.inspect(claim.connection)
        if inspected.error_code or inspected.identity is None:
            self.storage.fail(
                claim,
                inspected.error_code or "invalid_telegram_response",
                inspected.retry_after_seconds,
            )
            return None
        if inspected.webhook_configured:
            self.storage.fail(claim, "webhook_configured")
            return None
        identity = inspected.identity
        if claim.bot.telegram_id is not None and claim.bot.telegram_id != identity.id:
            self.storage.fail(claim, "bot_identity_changed")
            return None
        registered = self.storage.identity_registration(identity.id)
        if registered is not None and registered != claim.bot.id:
            self.storage.fail(claim, "bot_already_connected")
            return None
        return identity

    def poll(self, bot_id: UUID) -> None:
        claim = self.storage.claim(bot_id)
        if claim is None:
            return
        if not self.access.permitted(claim.bot.owner_id):
            self.storage.fail(claim, "access_revoked")
            return
        identity = self.identify(claim)
        if identity is None:
            return
        batch = self.telegram.updates(claim.connection, claim.bot.next_update_id)
        if batch.error_code:
            self.storage.fail(claim, batch.error_code, batch.retry_after_seconds)
            return
        if not self.access.permitted(claim.bot.owner_id):
            self.storage.fail(claim, "access_revoked")
            return
        pairing = self.storage.pairing_state(claim)
        now = timezone.now()
        fresh = tuple(
            update for update in batch.updates if update.update_id >= claim.bot.next_update_id
        )
        next_update_id = max(
            (update.update_id + 1 for update in fresh), default=claim.bot.next_update_id
        )
        outcome = self.storage.complete(
            claim,
            BotPollResult(
                identity=identity,
                updates=retained_updates(fresh, pairing),
                next_update_id=next_update_id,
                paired_chat_id=paired_chat(claim.bot, pairing, fresh, now),
                pairing_digest=pairing.digest,
                observed_at=now,
            ),
        )
        if outcome == BotCompletion.IDENTITY_CONFLICT:
            self.storage.fail(claim, "bot_already_connected")
