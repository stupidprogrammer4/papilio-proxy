from __future__ import annotations

import logging
from html import escape
from typing import Any, ClassVar

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile
from papilio_tasks.apps.schedulers import Scheduler

from papilio_proxy.modules.network.subscriptions.app.services import (
    AccessService,
    AccessUnavailable,
)
from papilio_proxy.modules.network.subscriptions.infra.qr import QrRenderer
from papilio_proxy.modules.network.subscriptions.infra.repository import MysqlAccessRepository
from papilio_proxy.modules.network.subscriptions.routers.cards import (
    delivery_caption,
    subscription_url,
)
from papilio_proxy.modules.network.subscriptions.routers.views import connection_links
from papilio_proxy.modules.sales.subscriptions.routers.telegram import _access_keyboard

logger = logging.getLogger(__name__)


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
                logger.warning(
                    "Usage alert delivery failed for alert %d: %s", alert.id, type(exc).__name__
                )
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


class ProvisionDeliveryDispatcher:
    def __init__(
        self,
        repository: MysqlAccessRepository,
        bot: Bot,
        public_base: str,
        access_service: AccessService | None = None,
    ) -> None:
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
                    current = await self._access_service.get_for_user(
                        access.telegram_id, access.subscription_id
                    )
                    if current is None:
                        raise AccessUnavailable("Active delivery is unavailable")
                    access = current
                url = subscription_url(self._public_base, access)
                image = await self._qr.render(url)
                await self._bot.send_photo(
                    access.telegram_id,
                    BufferedInputFile(image, filename="papilio-subscription.png"),
                    caption=delivery_caption(access, url),
                    reply_markup=_access_keyboard(
                        access.subscription_id, url, bool(access.hysteria_link)
                    ),
                )
                for index, link in enumerate(connection_links(access), 1):
                    label = "⚡ اتصال پیشنهادی" if index == 1 else f"🔗 اتصال جایگزین {index - 1}"
                    await self._bot.send_message(
                        access.telegram_id,
                        f"{label} · <b>{escape(access.profile_name)}</b>\n\n<code>{escape(link)}</code>",
                    )
            except (TelegramAPIError, ValueError, AccessUnavailable) as exc:
                await self._repository.release_delivery(notice.subscription_id)
                logger.warning(
                    "Provision delivery failed for order %s: %s",
                    notice.subscription_id[:8],
                    type(exc).__name__,
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
