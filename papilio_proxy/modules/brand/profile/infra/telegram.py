from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, FSInputFile, InputProfilePhotoStatic

from papilio_proxy.modules.brand.profile.domain.entities import BotBranding

LOGO_PATH = Path(__file__).resolve().parents[5] / "assets" / "papilio-logo-v2.png"

PUBLIC_COMMANDS = [
    BotCommand(command="start", description="صفحهٔ اصلی"),
    BotCommand(command="plans", description="دیدن پلن‌ها"),
    BotCommand(command="myservices", description="سرویس‌های من"),
    BotCommand(command="help", description="راهنمای استفاده"),
]


async def sync_bot_profile(bot: Bot, branding: BotBranding) -> None:
    """Publish DB-managed text and only commands that have real handlers."""
    name = await bot.get_my_name()
    short_description = await bot.get_my_short_description()
    description = await bot.get_my_description()
    commands = await bot.get_my_commands()
    updates: list[Callable[[], Awaitable[bool]]] = []
    if name.name != branding.name:
        updates.append(lambda: bot.set_my_name(name=branding.name))
    if short_description.short_description != branding.short_description:
        updates.append(
            lambda: bot.set_my_short_description(short_description=branding.short_description)
        )
    if description.description != branding.description:
        updates.append(lambda: bot.set_my_description(description=branding.description))
    if commands != PUBLIC_COMMANDS:
        updates.append(lambda: bot.set_my_commands(PUBLIC_COMMANDS))
    failure: TelegramAPIError | None = None
    for update in updates:
        try:
            await update()
        except TelegramAPIError as error:
            if failure is None:
                failure = error
    if failure is not None:
        raise failure


async def sync_bot_photo(bot: Bot) -> None:
    """Upload the existing square logo on explicit admin request, not every restart."""
    if not LOGO_PATH.is_file():
        raise FileNotFoundError("Bot profile logo is missing")
    await bot.set_my_profile_photo(photo=InputProfilePhotoStatic(photo=FSInputFile(LOGO_PATH)))
