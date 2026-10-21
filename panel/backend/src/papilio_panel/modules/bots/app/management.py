"""Operator-owned settings and administrative chat pairing."""

from uuid import UUID

from django.db import transaction

from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.shared.errors import Conflict, InvalidInput

from ..domain import BotChange, BotCreate, BotDefaults, BotPage, BotRead, BotSearch, PairingGrant
from ..interfaces import BotStorage, PairingIssuer
from .validation import create_digest, token_digest, validated_change, validated_create


class BotManagement:
    def __init__(
        self, storage: BotStorage, access: AdminAccessCapability, pairing: PairingIssuer
    ) -> None:
        self.storage = storage
        self.access = access
        self.pairing = pairing

    def defaults(self, actor_id: int) -> BotDefaults:
        self.access.authorize_actor(actor_id)
        return BotDefaults()

    @transaction.atomic
    def create(self, values: BotCreate) -> BotRead:
        self.access.authorize_actor(values.actor_id)
        validated = validated_create(values)
        digest = create_digest(validated)
        result = self.storage.create(validated, digest, token_digest(validated.token))
        if result.input_digest != digest:
            raise Conflict("This request key belongs to different bot settings.")
        return result.bot

    def read(self, bot_id: UUID, actor_id: int) -> BotRead:
        self.access.authorize_actor(actor_id)
        result = self.storage.read(bot_id, actor_id)
        return result

    def search(self, values: BotSearch) -> BotPage:
        self.access.authorize_actor(values.actor_id)
        if values.page < 1 or not 1 <= values.page_size <= 200:
            raise InvalidInput("Choose a positive page and page size from 1 to 200.")
        result = self.storage.search(values)
        return result

    @transaction.atomic
    def change(self, values: BotChange) -> BotRead:
        self.read(values.bot_id, values.actor_id)
        validated = validated_change(values)
        digest = token_digest(validated.token) if validated.token is not None else None
        result = self.storage.change(validated, digest)
        return result

    @transaction.atomic
    def pair(self, bot_id: UUID, actor_id: int) -> PairingGrant:
        bot = self.read(bot_id, actor_id)
        if not bot.verified or not bot.username or not bot.schedule.enabled:
            raise Conflict("Enable the bot and wait for verification before pairing.")
        secret = self.pairing.issue(bot.runtime.pairing_ttl_seconds)
        self.storage.set_pairing(bot, secret)
        return PairingGrant(
            url=f"https://t.me/{bot.username}?start={secret.parameter}",
            expires_at=secret.expires_at,
        )
