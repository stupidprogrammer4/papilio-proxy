"""Owner-authorized metadata/history queries and current recovery availability."""

from dataclasses import replace
from uuid import UUID

from django.utils import timezone

from papilio_panel.modules.bots.interfaces import BotCapability
from papilio_panel.modules.identity.interfaces import AdminAccessCapability

from ..domain import MessageRead
from ..interfaces import ShopMessageInspectionReader, ShopWorkInspectionReader
from ..recovery_contracts import (
    InspectionWindow,
    MessagePage,
    MessageRecoveryPage,
    MessageSearch,
    WorkInspection,
    WorkPage,
    WorkRecoveryPage,
    WorkSearch,
)
from .recovery_policy import message_actions, window, work_actions


class ShopWorkInspection:
    def __init__(
        self,
        reader: ShopWorkInspectionReader,
        access: AdminAccessCapability,
        bots: BotCapability,
        max_page_size: int,
    ) -> None:
        self.reader = reader
        self.access = access
        self.bots = bots
        self.max_page_size = max_page_size

    def read(self, bot_id: UUID, work_id: UUID, actor_id: int) -> WorkInspection:
        self.access.authorize_owner(actor_id)
        self.bots.read(bot_id, actor_id)
        record = self.reader.read(bot_id, work_id, actor_id)
        return replace(record, actions=work_actions(record, timezone.now()))

    def search(self, values: WorkSearch) -> WorkPage:
        self.access.authorize_owner(values.actor_id)
        self.bots.read(values.bot_id, values.actor_id)
        window(values, self.max_page_size)
        page = self.reader.search(values)
        now = timezone.now()
        return replace(
            page, items=tuple(replace(row, actions=work_actions(row, now)) for row in page.items)
        )

    def history(self, work_id: UUID, values: InspectionWindow) -> WorkRecoveryPage:
        self.read(values.bot_id, work_id, values.actor_id)
        window(values, self.max_page_size)
        result = self.reader.history(work_id, values)
        return result


class ShopMessageInspection:
    def __init__(
        self,
        reader: ShopMessageInspectionReader,
        access: AdminAccessCapability,
        bots: BotCapability,
        max_page_size: int,
    ) -> None:
        self.reader = reader
        self.access = access
        self.bots = bots
        self.max_page_size = max_page_size

    def read(self, bot_id: UUID, message_id: UUID, actor_id: int) -> MessageRead:
        self.access.authorize_owner(actor_id)
        self.bots.read(bot_id, actor_id)
        record = self.reader.read(bot_id, message_id, actor_id)
        return replace(record, actions=message_actions(record, timezone.now()))

    def search(self, values: MessageSearch) -> MessagePage:
        self.access.authorize_owner(values.actor_id)
        self.bots.read(values.bot_id, values.actor_id)
        window(values, self.max_page_size)
        page = self.reader.search(values)
        now = timezone.now()
        return replace(
            page, items=tuple(replace(row, actions=message_actions(row, now)) for row in page.items)
        )

    def history(self, message_id: UUID, values: InspectionWindow) -> MessageRecoveryPage:
        self.read(values.bot_id, message_id, values.actor_id)
        window(values, self.max_page_size)
        result = self.reader.history(message_id, values)
        return result
