from __future__ import annotations

import logging
from html import escape
from typing import Any, ClassVar
from urllib.parse import quote

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile
from dishka import Provider, Scope, provide
from papilio_tasks.apps.schedulers import Scheduler

from bot.infra.db.access import MysqlAccessRepository
from bot.infra.qr import QrRenderer
from bot.presentation.subscription_view import connection_links
from bot.presentation.ui import _access_keyboard
from bot.services.access import AccessService, AccessUnavailable
from bot.services.node import NodeReconciler
from bot.services.payments import PaymentVerificationService

logger = logging.getLogger(__name__)


class PaymentRecheckJob(Scheduler):
    schedule: ClassVar[list[dict[str, Any]] | None] = [{"interval": 15}]

    def __init__(self, service: PaymentVerificationService) -> None:
        self._service = service

    async def run(self) -> int:
        return await self._service.recheck_pending()


class PaymentRecheckProvider(Provider):
    scope = Scope.APP

    def __init__(self, service: PaymentVerificationService) -> None:
        super().__init__()
        self._service = service

    @provide
    def job(self) -> PaymentRecheckJob:
        return PaymentRecheckJob(self._service)


class UsageWarningDispatcher:
    def __init__(self, repository: MysqlAccessRepository, bot: Bot) -> None:
        self._repository = repository
        self._bot = bot

    async def send_pending(self) -> int:
        sent = 0
        for alert in await self._repository.claim_alerts():
            used_gib = alert.traffic_used_bytes / 1024**3
            remaining_gib = max(0, alert.traffic_limit_bytes - alert.traffic_used_bytes) / 1024**3
            try:
                await self._bot.send_message(
                    alert.telegram_id,
                    "⚠️ <b>۸۰٪ حجم اشتراکت مصرف شده</b>\n\n"
                    f"📊 مصرف تا آخرین اندازه‌گیری: {used_gib:.2f} گیگابایت\n"
                    f"✨ باقیمانده: {remaining_gib:.2f} گیگابایت\n\n"
                    "برای دیدن وضعیت تازه، «سرویس‌های من» را باز کن.",
                )
            except TelegramAPIError as exc:
                await self._repository.release_alert(alert.id)
                logger.warning("Usage alert delivery failed for alert %d: %s", alert.id, type(exc).__name__)
            else:
                await self._repository.mark_alert_sent(alert.id)
                sent += 1
        return sent


class UsageWarningJob(Scheduler):
    schedule: ClassVar[list[dict[str, Any]] | None] = [{"interval": 60}]

    def __init__(self, dispatcher: UsageWarningDispatcher) -> None:
        self._dispatcher = dispatcher

    async def run(self) -> int:
        return await self._dispatcher.send_pending()


class UsageWarningProvider(Provider):
    scope = Scope.APP

    def __init__(self, dispatcher: UsageWarningDispatcher) -> None:
        super().__init__()
        self._dispatcher = dispatcher

    @provide
    def job(self) -> UsageWarningJob:
        return UsageWarningJob(self._dispatcher)


class NodeReconcileJob(Scheduler):
    schedule: ClassVar[list[dict[str, Any]] | None] = [{"interval": 2}]

    def __init__(self, reconciler: NodeReconciler) -> None:
        self._reconciler = reconciler

    async def run(self) -> None:
        await self._reconciler.run_once()


class NodeReconcileProvider(Provider):
    scope = Scope.APP

    def __init__(self, reconciler: NodeReconciler) -> None:
        super().__init__()
        self._reconciler = reconciler

    @provide
    def job(self) -> NodeReconcileJob:
        return NodeReconcileJob(self._reconciler)


class ProvisionDeliveryDispatcher:
    def __init__(self, repository: MysqlAccessRepository, bot: Bot, public_base: str,
                 access_service: AccessService | None = None) -> None:
        self._repository = repository
        self._bot = bot
        self._public_base = public_base
        self._qr = QrRenderer()
        self._access_service = access_service

    async def send_pending(self) -> int:
        sent = 0
        for notice in await self._repository.claim_deliveries():
            access = notice.access
            try:
                if self._access_service:
                    current = await self._access_service.get_for_user(access.telegram_id, access.subscription_id)
                    if current is None:
                        raise AccessUnavailable("Active delivery is unavailable")
                    access = current
                subscription_url = f"{self._public_base}/s/{access.token}#{quote(access.profile_name[:40], safe='')}"
                image = await self._qr.render(subscription_url)
                await self._bot.send_photo(
                    access.telegram_id,
                    BufferedInputFile(image, filename="papilio-subscription.png"),
                    caption=(
                        "🦋 <b>سرویس پاپیلیو فعال شد!</b>\n\n"
                        "📲 QR اشتراک اختصاصی توست.\n"
                        f"🔗 لینک اشتراک و مشاهدهٔ مصرف:\n<code>{escape(subscription_url)}</code>\n\n"
                        "🔐 لینک‌ها را برای دیگران نفرست."
                    ),
                    reply_markup=_access_keyboard(access.subscription_id, subscription_url, bool(access.hysteria_link)),
                )
                for link in connection_links(access):
                    protocol = "🚀 Hysteria2" if link.startswith("hysteria2:") else "⚡ VLESS" if link.startswith("vless:") else "🌐 VMess"
                    await self._bot.send_message(access.telegram_id,
                        f"{protocol} · <b>{escape(access.profile_name)}</b>\n\n<code>{escape(link)}</code>\n\n"
                        "📊 حجم همهٔ مسیرها مشترک است؛ مصرف و مانده در ساب نمایش داده می‌شود.")
            except (TelegramAPIError, ValueError, AccessUnavailable) as exc:
                await self._repository.release_delivery(notice.subscription_id)
                logger.warning(
                    "Provision delivery failed for order %s: %s",
                    notice.subscription_id[:8], type(exc).__name__,
                )
            else:
                await self._repository.mark_delivery_sent(notice.subscription_id)
                sent += 1
        return sent


class ProvisionDeliveryJob(Scheduler):
    schedule: ClassVar[list[dict[str, Any]] | None] = [{"interval": 5}]

    def __init__(self, dispatcher: ProvisionDeliveryDispatcher) -> None:
        self._dispatcher = dispatcher

    async def run(self) -> int:
        return await self._dispatcher.send_pending()


class ProvisionDeliveryProvider(Provider):
    scope = Scope.APP

    def __init__(self, dispatcher: ProvisionDeliveryDispatcher) -> None:
        super().__init__()
        self._dispatcher = dispatcher

    @provide
    def job(self) -> ProvisionDeliveryJob:
        return ProvisionDeliveryJob(self._dispatcher)
