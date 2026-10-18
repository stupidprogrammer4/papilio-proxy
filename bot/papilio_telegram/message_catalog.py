"""Translate fixed bot copy at the Telegram request boundary."""

import re
from functools import lru_cache
from typing import Any

from aiogram import Bot
from aiogram.client.session.middlewares.base import (
    BaseRequestMiddleware,
    NextRequestMiddlewareType,
)
from aiogram.methods import TelegramMethod
from aiogram.methods.base import Response
from aiogram.types import InlineKeyboardMarkup

from papilio_telegram.api import BotApi


@lru_cache(maxsize=16)
def _source_pattern(sources: tuple[str, ...]) -> re.Pattern[str] | None:
    if not sources:
        return None
    alternatives = "|".join(re.escape(source) for source in sources)
    return re.compile(alternatives)


def translate_fixed_text(text: str, catalog: dict[str, str]) -> str:
    replacements = {
        source: translated
        for source, translated in catalog.items()
        if source and translated and translated != source
    }
    pattern = _source_pattern(
        tuple(sorted(replacements, key=len, reverse=True))
    )
    if pattern is None:
        return text
    return pattern.sub(lambda match: replacements[match.group(0)], text)


def _translate_markup(
    markup: InlineKeyboardMarkup, catalog: dict[str, str]
) -> InlineKeyboardMarkup:
    rows = [
        [
            button.model_copy(
                update={"text": translate_fixed_text(button.text, catalog)}
            )
            for button in row
        ]
        for row in markup.inline_keyboard
    ]
    return markup.model_copy(update={"inline_keyboard": rows})


class BotMessageCatalogMiddleware(BaseRequestMiddleware):
    def __init__(self, api: BotApi) -> None:
        self.api = api

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[Any],
        bot: Bot,
        method: TelegramMethod[Any],
    ) -> Response[Any]:
        catalog = self.api.presentation.message_catalog
        updates: dict[str, Any] = {}
        for field in ("text", "caption"):
            value = getattr(method, field, None)
            if isinstance(value, str):
                updates[field] = translate_fixed_text(value, catalog)
        markup = getattr(method, "reply_markup", None)
        if isinstance(markup, InlineKeyboardMarkup):
            updates["reply_markup"] = _translate_markup(markup, catalog)
        translated_method = method.model_copy(update=updates)
        response = await make_request(bot, translated_method)
        return response


def install_bot_message_catalog(bot: Bot, api: BotApi) -> None:
    bot.session.middleware.register(BotMessageCatalogMiddleware(api))
