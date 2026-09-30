from __future__ import annotations

from pathlib import Path

from aiogram import Bot
from aiogram.types import BotCommand, FSInputFile, InputProfilePhotoStatic

from bot.models.branding import BotBranding

LOGO_PATH = Path(__file__).resolve().parents[2] / "assets" / "papilio-logo.png"

PUBLIC_COMMANDS = [
    BotCommand(command="start", description="صفحهٔ اصلی"),
    BotCommand(command="plans", description="دیدن پلن‌ها"),
    BotCommand(command="myservices", description="سرویس‌های من"),
    BotCommand(command="help", description="راهنمای استفاده"),
]


async def sync_bot_profile(bot: Bot, branding: BotBranding) -> None:
    """Publish DB-managed text and only commands that have real handlers."""
    await bot.set_my_name(name=branding.name)
    await bot.set_my_short_description(short_description=branding.short_description)
    await bot.set_my_description(description=branding.description)
    await bot.set_my_commands(PUBLIC_COMMANDS)


async def sync_bot_photo(bot: Bot) -> None:
    """Upload the existing square logo on explicit admin request, not every restart."""
    if not LOGO_PATH.is_file():
        raise FileNotFoundError("Bot profile logo is missing")
    await bot.set_my_profile_photo(photo=InputProfilePhotoStatic(photo=FSInputFile(LOGO_PATH)))
