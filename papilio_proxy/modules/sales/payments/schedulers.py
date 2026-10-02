import asyncio
import logging
from html import escape
from typing import Any, ClassVar

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from papilio_tasks.apps.schedulers import Scheduler

from papilio_proxy.modules.sales.payments.domain.entities import ReceiptNotification, ReceiptStatus
from papilio_proxy.modules.sales.payments.infra.repository import MysqlPaymentRepository

logger = logging.getLogger(__name__)


class ReceiptDecisionJob(Scheduler):
    schedule: ClassVar[list[dict[str, Any]] | None] = [{"interval": 5}]

    def __init__(self, repository: MysqlPaymentRepository, bot: Bot) -> None:
        self._repository = repository
        self._bot = bot

    async def _send(self, notice: ReceiptNotification) -> bool:
        if notice.status == ReceiptStatus.APPROVED:
            text = "✅ <b>پرداختت تأیید شد.</b>\n\nاشتراکت در حال آماده‌سازی است؛ لینک و QR در همین چت ارسال می‌شوند."
            button = InlineKeyboardButton(
                text="🧾 پیگیری خرید", callback_data="orders", style="success"
            )
        else:
            text = "❌ <b>رسیدت تأیید نشد.</b>\n\n" + escape(notice.reason)
            button = InlineKeyboardButton(
                text="📸 ارسال رسید جدید",
                callback_data=f"receipt:{notice.order_id}",
                style="primary",
            )
        try:
            await self._bot.send_message(
                notice.telegram_id,
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[button]]),
            )
        except TelegramAPIError as exc:
            logger.warning("Receipt result delivery failed: %s", type(exc).__name__)
            await self._repository.finish_notification(notice.receipt_id, sent=False)
            return False
        await self._repository.finish_notification(notice.receipt_id, sent=True)
        return True

    async def run(self) -> int:
        notices = await self._repository.claim_notifications()
        return sum(await asyncio.gather(*(self._send(notice) for notice in notices)))
