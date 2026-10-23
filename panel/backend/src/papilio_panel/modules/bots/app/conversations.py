"""Authorize private incoming identities and current bot transport operations."""

from uuid import UUID

from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.shared.errors import Conflict, InvalidInput, Missing

from ..domain import BotEventRead, BotReplyRequest, TelegramFileResult, TelegramSendResult
from ..interfaces import BotEventStorage, TelegramConversationGateway


class BotConversations:
    def __init__(
        self,
        storage: BotEventStorage,
        access: AdminAccessCapability,
        telegram: TelegramConversationGateway,
    ) -> None:
        self.storage = storage
        self.access = access
        self.telegram = telegram

    def event(self, event_id: int) -> BotEventRead:
        result = self.storage.read(event_id)
        self.access.authorize_owner(result.bot.owner_id)
        return result

    def processed(self, event_id: int, bot_id: UUID, owner_id: int) -> None:
        event = self.event(event_id)
        if event.bot.id != bot_id or event.bot.owner_id != owner_id:
            raise Missing("The incoming Telegram event was not found on this bot.")
        self.storage.processed(event_id, bot_id, owner_id)

    def reply(self, values: BotReplyRequest) -> TelegramSendResult:
        event = self.event(values.event_id)
        if event.bot.id != values.bot_id or event.bot.owner_id != values.owner_id:
            raise Missing("The incoming Telegram event was not found on this bot.")
        if event.message is None:
            raise Conflict("Only verified private user messages can receive shop replies.")
        chat_id = event.bot.admin_chat_id if values.administrator else event.message.chat_id
        if chat_id is None:
            raise Conflict("Pair this bot's administrator chat before sending notifications.")
        if not values.reply.text or len(values.reply.text.encode("utf-16-le")) > 8192:
            raise InvalidInput("Telegram messages must contain one to 4096 UTF-16 units.")
        connection = self.storage.connection(event.bot.id, event.bot.owner_id, event.bot.revision)
        if event.message.callback_id is not None:
            self.telegram.answer(connection, event.message.callback_id)
        result = self.telegram.send(connection, chat_id, values.reply)
        return result

    def file(self, event_id: int, max_bytes: int) -> TelegramFileResult:
        event = self.event(event_id)
        if event.message is None or event.message.file is None:
            raise Missing("This private Telegram event has no receipt attachment.")
        if type(max_bytes) is not int or max_bytes < 1:
            raise InvalidInput("Choose a positive attachment byte limit.")
        connection = self.storage.connection(event.bot.id, event.bot.owner_id, event.bot.revision)
        result = self.telegram.download(
            connection, event.message.file, min(max_bytes, event.bot.runtime.max_response_bytes)
        )
        return result
