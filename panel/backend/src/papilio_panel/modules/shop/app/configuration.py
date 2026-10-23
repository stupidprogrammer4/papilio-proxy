"""Authorize per-bot shop settings without resetting operator choices."""

from uuid import UUID

from django.db import transaction

from papilio_panel.modules.bots.interfaces import BotCapability
from papilio_panel.modules.identity.interfaces import AdminAccessCapability

from ..domain import ShopDefinition, ShopSettingsChange, ShopSettingsCreate, ShopSettingsRead
from ..interfaces import ShopSettingsStorage
from .validation import definition, revision


class ShopConfiguration:
    def __init__(
        self,
        storage: ShopSettingsStorage,
        access: AdminAccessCapability,
        bots: BotCapability,
        max_page_size: int,
    ) -> None:
        self.storage = storage
        self.access = access
        self.bots = bots
        self.max_page_size = max_page_size

    def defaults(self, actor_id: int) -> ShopDefinition:
        self.access.authorize_owner(actor_id)
        return ShopDefinition()

    def read(self, bot_id: UUID, actor_id: int) -> ShopSettingsRead:
        self.access.authorize_owner(actor_id)
        self.bots.read(bot_id, actor_id)
        result = self.storage.read(bot_id, actor_id)
        return result

    @transaction.atomic
    def create(self, values: ShopSettingsCreate) -> ShopSettingsRead:
        self.access.authorize_owner(values.actor_id)
        self.bots.read(values.bot_id, values.actor_id)
        definition(values.definition, self.max_page_size)
        result = self.storage.create(values)
        return result

    @transaction.atomic
    def change(self, values: ShopSettingsChange) -> ShopSettingsRead:
        self.read(values.bot_id, values.actor_id)
        definition(values.definition, self.max_page_size)
        revision(values.expected_revision)
        result = self.storage.change(values)
        return result
