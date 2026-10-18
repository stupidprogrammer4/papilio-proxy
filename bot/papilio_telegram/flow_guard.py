from collections.abc import Awaitable, Callable
from typing import Any, Literal

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

from papilio_telegram.api import BotApi, BotApiError
from papilio_telegram.commerce import BotPresentation
from papilio_telegram.locales import telegram_locale

BotFlow = Literal[
    "purchases",
    "loyalty",
    "trial",
    "account",
    "catalog",
    "subscriptions",
    "wallet",
    "support",
]

_EXACT_CALLBACK_FLOWS: dict[str, BotFlow] = {
    "loyalty": "loyalty",
    "trial": "trial",
    "trial_claim": "trial",
    "account": "account",
    "wallet": "wallet",
    "support": "support",
}
_PREFIX_CALLBACK_FLOWS: tuple[tuple[str, BotFlow], ...] = (
    ("ch:", "purchases"),
    ("plans:", "catalog"),
    ("plan:", "catalog"),
    ("buy:", "catalog"),
    ("cb:", "catalog"),
    ("cf:", "catalog"),
    ("cd:", "catalog"),
    ("cp:", "catalog"),
    ("cx:", "catalog"),
    ("ct:", "catalog"),
    ("ci:", "catalog"),
    ("cc:", "catalog"),
    ("co:", "catalog"),
    ("cr:", "catalog"),
    ("topup:", "wallet"),
    ("subs:", "subscriptions"),
    ("service:", "subscriptions"),
    ("rotate:", "subscriptions"),
    ("renewal-status:", "subscriptions"),
    ("renew:", "subscriptions"),
)


def callback_flow(callback_data: str) -> BotFlow | None:
    exact_flow = _EXACT_CALLBACK_FLOWS.get(callback_data)
    if exact_flow is not None:
        return exact_flow

    flow: BotFlow | None = next(
        (
            selected_flow
            for prefix, selected_flow in _PREFIX_CALLBACK_FLOWS
            if callback_data.startswith(prefix)
        ),
        None,
    )
    return flow


def flow_is_visible(presentation: BotPresentation, callback_data: str) -> bool:
    flow = callback_flow(callback_data)
    if flow is None:
        return True

    button = next(
        (item for item in presentation.menu_buttons if item.action == flow),
        None,
    )
    return button is None or button.visible


class BotFlowGuard(BaseMiddleware):
    def __init__(self, api: BotApi) -> None:
        self.api = api

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, CallbackQuery):
            try:
                await self.api.refresh_presentation(
                    telegram_locale(event.from_user.language_code)
                )
            except BotApiError:
                await event.answer(
                    "تنظیمات این بخش در دسترس نیست؛ دوباره تلاش کنید.",
                    show_alert=True,
                )
                return None
            callback_data = event.data or ""
            if not flow_is_visible(self.api.presentation, callback_data):
                await event.answer(
                    "این بخش در حال حاضر غیرفعال است.", show_alert=True
                )
                return None

        result = await handler(event, data)
        return result
