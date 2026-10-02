from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack

import httpx
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError

from bot.core.config import ConfigurationError, Settings
from bot.infra.db.access import MysqlAccessRepository
from bot.infra.db.checkout import MysqlCheckoutRepository
from bot.infra.db.credentials import MysqlCredentialVault
from bot.infra.db.mysql import MysqlSubscriptionRepository
from bot.infra.db.payments import MysqlPaymentRepository
from bot.infra.kpay import KpayVerifier
from bot.infra.node import XrayNodeClient
from bot.jobs.runtime import usage_warning_scheduler
from bot.presentation.admin import build_admin_router
from bot.presentation.admin_branding import build_branding_router
from bot.presentation.profile import sync_bot_profile
from bot.presentation.ui import build_router
from bot.services.access import AccessService
from bot.services.admin_plans import AdminPlanService
from bot.services.branding import BrandingService
from bot.services.checkout import CheckoutService
from bot.services.node import NodeReconciler
from bot.services.payments import PaymentVerificationService
from bot.services.subscriptions import SubscriptionService

logger = logging.getLogger(__name__)


async def run() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
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
        access_service.node_links = node_client.hysteria_link
        reconciler = NodeReconciler(access_repository, access_service, node_client)
    dispatcher = Dispatcher()
    checkout_repository: MysqlCheckoutRepository | None = None
    payment_repository: MysqlPaymentRepository | None = None
    vault: MysqlCredentialVault | None = None
    payment_client: httpx.AsyncClient | None = None
    checkout_service: CheckoutService | None = None
    if settings.kpay_api_base_url and settings.credential_encryption_key:
        checkout_repository = MysqlCheckoutRepository(settings.database_url)
        payment_repository = MysqlPaymentRepository(settings.database_url)
        await checkout_repository.initialize()
        await payment_repository.initialize()
        vault = MysqlCredentialVault(settings.database_url, settings.credential_encryption_key)
        payment_client = httpx.AsyncClient(timeout=12, follow_redirects=False)
        provider = KpayVerifier(settings.kpay_api_base_url, vault, payment_client)
        verification = PaymentVerificationService(provider, payment_repository)
        checkout_service = CheckoutService(
            checkout_repository, provider, payment_repository, verification, settings.admin_ids
        )
    subscription_service = SubscriptionService(repository, repository)
    dispatcher.include_router(build_router(subscription_service, settings, access_service, checkout_service))
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
        if payment_client is not None:
            await payment_client.aclose()
        if vault is not None:
            await vault.close()
        if checkout_repository is not None:
            await checkout_repository.close()
        if payment_repository is not None:
            await payment_repository.close()
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
