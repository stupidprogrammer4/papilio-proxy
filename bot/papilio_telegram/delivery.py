import asyncio
import hmac
import re
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp import web

from papilio_telegram.api import BotApi, BotApiError
from papilio_telegram.commerce import (
    CheckoutNoticeAction,
    SubscriptionNoticeAction,
)
from papilio_telegram.config import BotSettings
from papilio_telegram.presentation import trial_service_menu


def notice_menu(
    action: SubscriptionNoticeAction | CheckoutNoticeAction | None,
) -> InlineKeyboardMarkup | None:
    if isinstance(action, CheckoutNoticeAction):
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="بررسی وضعیت همین خرید",
                        callback_data=f"ci:{action.checkout_id}",
                    )
                ]
            ]
        )
    if isinstance(action, SubscriptionNoticeAction):
        return trial_service_menu(action.subscription_id)
    return None


def register_delivery(
    application: web.Application, bot: Bot, api: BotApi, settings: BotSettings
) -> None:
    async def deliver(request: web.Request) -> web.Response:
        key = request.headers.get("X-Papilio-Delivery-Key", "")
        if (
            not key
            or not key.isascii()
            or not settings.notification_delivery_key
            or not hmac.compare_digest(key, settings.notification_delivery_key)
        ):
            raise web.HTTPUnauthorized()
        if not settings.notification_delivery_enabled:
            return web.json_response(
                {
                    "outcome": "retryable",
                    "error_code": "notification_outbound_disabled",
                }
            )
        try:
            payload = await request.clone(
                client_max_size=settings.notification_max_request_bytes
            ).json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest()
        id, token = payload.get("notification_id"), payload.get("claim_token")
        if (
            type(id) is not int
            or id <= 0
            or not isinstance(token, str)
            or not re.fullmatch(r"[a-f0-9]{64}", token)
        ):
            raise web.HTTPBadRequest()
        try:
            authorization = await api.authorize_notification(id, token)
        except BotApiError:
            return web.json_response(
                {
                    "outcome": "retryable",
                    "error_code": "notification_authorization_unavailable",
                }
            )
        if not authorization.allowed:
            return web.json_response(
                {
                    "outcome": "ambiguous",
                    "error_code": "notification_send_not_authorized",
                }
            )
        recipient, text, lease = (
            authorization.telegram_id,
            authorization.text,
            authorization.lease_until,
        )
        if (
            type(recipient) is not int
            or not isinstance(text, str)
            or not isinstance(lease, datetime)
        ):
            return web.json_response(
                {
                    "outcome": "rejected",
                    "error_code": "notification_authorization_invalid",
                }
            )
        deadline = lease
        if (
            deadline.tzinfo is None
            or datetime.now(UTC)
            + timedelta(
                seconds=settings.notification_send_timeout_seconds
                + settings.notification_lease_margin_seconds
            )
            >= deadline
        ):
            return web.json_response(
                {
                    "outcome": "retryable",
                    "error_code": "notification_send_deadline",
                }
            )
        try:
            async with asyncio.timeout(
                settings.notification_send_timeout_seconds
            ):
                message = await bot.send_message(
                    recipient,
                    text,
                    parse_mode=None,
                    disable_web_page_preview=True,
                    reply_markup=notice_menu(authorization.action),
                )
            return web.json_response(
                {"outcome": "accepted", "message_id": message.message_id}
            )
        except TelegramRetryAfter as error:
            return web.json_response(
                {
                    "outcome": "retryable",
                    "error_code": "telegram_retry_after",
                    "retry_after_seconds": error.retry_after,
                }
            )
        except TelegramForbiddenError:
            return web.json_response(
                {
                    "outcome": "rejected",
                    "error_code": "telegram_recipient_forbidden",
                }
            )
        except TelegramBadRequest:
            return web.json_response(
                {
                    "outcome": "rejected",
                    "error_code": "telegram_request_rejected",
                }
            )
        except (TelegramNetworkError, TimeoutError, TelegramAPIError):
            return web.json_response(
                {
                    "outcome": "ambiguous",
                    "error_code": "telegram_delivery_uncertain",
                }
            )

    application.router.add_post("/internal/notifications/deliver", deliver)
