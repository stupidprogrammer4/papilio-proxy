from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.core.config import ConfigurationError, Settings
from bot.infra.db.mysql import MysqlSubscriptionRepository
from bot.presentation.admin import build_admin_router
from bot.presentation.ui import build_router
from bot.services.admin_plans import AdminPlanService
from bot.services.subscriptions import SubscriptionService


async def run() -> None:
    settings = Settings.from_environment()
    repository = MysqlSubscriptionRepository(settings.database_url)
    assert settings.bot_token is not None
    await repository.initialize()
    dispatcher = Dispatcher()
    subscription_service = SubscriptionService(repository, repository)
    dispatcher.include_router(build_router(subscription_service, settings))
    dispatcher.include_router(build_admin_router(AdminPlanService(repository, settings.admin_ids)))
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await bot.session.close()
        await repository.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        asyncio.run(run())
    except ConfigurationError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
