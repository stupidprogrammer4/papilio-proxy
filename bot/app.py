from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError

from bot.core.config import ConfigurationError, Settings
from bot.infra.db.access import MysqlAccessRepository
from bot.infra.db.mysql import MysqlSubscriptionRepository
from bot.infra.node import XrayNodeClient
from bot.jobs.runtime import usage_warning_scheduler
from bot.presentation.admin import build_admin_router
from bot.presentation.admin_branding import build_branding_router
from bot.presentation.profile import sync_bot_profile
from bot.presentation.ui import build_router
from bot.services.access import AccessService
from bot.services.admin_plans import AdminPlanService
from bot.services.branding import BrandingService
from bot.services.node import NodeReconciler
from bot.services.subscriptions import SubscriptionService

logger = logging.getLogger(__name__)


async def run() -> None:
    settings = Settings.from_environment()
    repository = MysqlSubscriptionRepository(settings.database_url)
    assert settings.bot_token is not None
    await repository.initialize()
    access_repository: MysqlAccessRepository | None = None
    access_service: AccessService | None = None
    if settings.credential_encryption_key:
        access_repository = MysqlAccessRepository(
            settings.database_url, settings.credential_encryption_key
        )
        await access_repository.initialize()
        access_service = AccessService(access_repository)
    node_client: XrayNodeClient | None = None
    reconciler: NodeReconciler | None = None
    if (
        settings.node_socket_path and settings.subscription_public_base_url
        and access_repository is not None and access_service is not None
    ):
        node_client = XrayNodeClient(settings.node_socket_path)
        reconciler = NodeReconciler(access_repository, access_service, node_client)
    dispatcher = Dispatcher()
    subscription_service = SubscriptionService(repository, repository)
    dispatcher.include_router(build_router(subscription_service, settings, access_service))
    dispatcher.include_router(build_admin_router(AdminPlanService(repository, settings.admin_ids)))
    branding_service = BrandingService(repository)
    dispatcher.include_router(build_branding_router(branding_service, settings.admin_ids))
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        try:
            await sync_bot_profile(bot, await branding_service.get())
        except TelegramAPIError as exc:
            logger.warning("Bot profile sync failed: %s", type(exc).__name__)
        async with AsyncExitStack() as stack:
            if node_client is not None:
                stack.push_async_callback(node_client.close)
            if access_repository is not None:
                await stack.enter_async_context(
                    usage_warning_scheduler(
                        access_repository, bot, reconciler, settings.subscription_public_base_url
                    )
                )
            await dispatcher.start_polling(
                bot, allowed_updates=dispatcher.resolve_used_update_types()
            )
    finally:
        await bot.session.close()
        await repository.close()
        if access_repository is not None:
            await access_repository.close()


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
