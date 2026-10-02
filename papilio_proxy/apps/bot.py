import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError
from dishka import make_async_container
from papilio.core.bootstrap import Bootstrapper

from papilio_proxy.apps.scheduler import run_schedulers
from papilio_proxy.config.database import Base, DatabaseConnection
from papilio_proxy.config.providers import RuntimeProvider
from papilio_proxy.config.settings import ConfigurationError, Settings
from papilio_proxy.modules.brand.profile.app.services import BrandingService
from papilio_proxy.modules.brand.profile.infra.telegram import sync_bot_profile
from papilio_proxy.modules.brand.profile.routers.telegram import build_branding_router
from papilio_proxy.modules.network.subscriptions.app.services import AccessService
from papilio_proxy.modules.sales.payments.app.services import PaymentService
from papilio_proxy.modules.sales.subscriptions.app.plans import AdminPlanService
from papilio_proxy.modules.sales.subscriptions.app.services import SubscriptionService
from papilio_proxy.modules.sales.subscriptions.routers.telegram import build_router
from papilio_proxy.modules.sales.subscriptions.routers.telegram_admin import build_admin_router

logger = logging.getLogger(__name__)


async def run() -> None:
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    settings = Settings.from_environment()
    bootstrap = Bootstrapper(["papilio_proxy.modules"])
    container = make_async_container(RuntimeProvider(settings), *bootstrap.boot_providers())
    try:
        database = await container.get(DatabaseConnection)
        async with database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        bot = await container.get(Bot)
        subscriptions = await container.get(SubscriptionService)
        payments = await container.get(PaymentService)
        access = await container.get(AccessService)
        branding = await container.get(BrandingService)
        dispatcher = Dispatcher()
        dispatcher.include_router(build_router(subscriptions, settings, access, payments))
        dispatcher.include_router(build_admin_router(await container.get(AdminPlanService)))
        dispatcher.include_router(build_branding_router(branding, settings.admin_ids))
        profile = await branding.get()
        if all((profile.name, profile.description, profile.short_description)):
            try:
                await sync_bot_profile(bot, profile)
            except TelegramAPIError as exc:
                logger.warning("Bot profile sync failed: %s", type(exc).__name__)
        async with run_schedulers(container):
            await dispatcher.start_polling(
                bot, allowed_updates=dispatcher.resolve_used_update_types(), close_bot_session=False
            )
    finally:
        await container.close()


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
