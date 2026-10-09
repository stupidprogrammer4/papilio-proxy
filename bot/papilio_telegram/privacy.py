from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

_PRIVATE_CHAT_NOTICE = (
    "برای استفاده از حساب و سرویس‌ها، گفت‌وگوی خصوصی بات را باز کنید."
)


class PrivateChatGuard(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            authorized = (
                event.chat.type == "private"
                and event.from_user is not None
                and event.chat.id == event.from_user.id
            )
            if not authorized:
                await event.answer(_PRIVATE_CHAT_NOTICE)
                return None
        elif isinstance(event, CallbackQuery):
            message = event.message
            authorized = (
                isinstance(message, Message)
                and message.chat.type == "private"
                and message.chat.id == event.from_user.id
            )
            if not authorized:
                await event.answer(_PRIVATE_CHAT_NOTICE, show_alert=True)
                return None
        else:
            return None
        result = await handler(event, data)
        return result
