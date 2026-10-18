import asyncio
from typing import Any

from aiogram import Bot
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.methods.base import Response
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp import web

from papilio_telegram.api import BotApi
from papilio_telegram.commerce import BotPresentation
from papilio_telegram.config import BotApiLimits
from papilio_telegram.message_catalog import (
    BotMessageCatalogMiddleware,
    translate_fixed_text,
)


def test_catalog_translates_fixed_fragments_and_preserves_dynamic_values() -> (
    None
):
    text = "قیمت فعلی: Plan A · 12,000 تومان"
    translated = translate_fixed_text(
        text,
        {"قیمت فعلی: ": "Current price: ", " تومان": " toman"},
    )

    assert translated == "Current price: Plan A · 12,000 toman"


def test_api_refresh_reads_the_locale_catalog_over_http() -> None:
    async def respond(request: web.Request) -> web.Response:
        assert request.query["locale"] == "ru"
        return web.json_response(
            {
                "data": {
                    "message_catalog": {
                        "درخواست انجام نشد.": "Не удалось выполнить запрос."
                    }
                }
            }
        )

    async def execute() -> None:
        app = web.Application()
        app.router.add_get("/v1/bot/presentation", respond)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        api = BotApi(
            f"http://127.0.0.1:{runner.addresses[0][1]}",
            "controlled-test-key",
            2.0,
            BotApiLimits(65536, 8, 8192, 15, 60),
        )
        try:
            await api.refresh_presentation("ru")
            assert (
                api.presentation.message_catalog["درخواست انجام نشد."]
                == "Не удалось выполнить запрос."
            )
            assert (
                translate_fixed_text(
                    "درخواست انجام نشد. Plan A",
                    api.presentation.message_catalog,
                )
                == "Не удалось выполнить запрос. Plan A"
            )
        finally:
            await api.close()
            await runner.cleanup()

    asyncio.run(execute())


def test_telegram_request_middleware_translates_text_and_buttons() -> None:
    api = BotApi(
        "https://api.example.test",
        "secret",
        2.0,
        BotApiLimits(65536, 8, 8192, 15, 60),
    )
    api._presentation.set(
        BotPresentation(
            message_catalog={
                "درخواست انجام نشد.": "The request failed.",
                "↩️ بازگشت": "↩️ Back",
            }
        )
    )
    middleware = BotMessageCatalogMiddleware(api)
    bot = Bot("123456:abcdef")
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="↩️ بازگشت", callback_data="home")]
        ]
    )
    request = SendMessage(
        chat_id=1,
        text="درخواست انجام نشد. Dynamic plan title",
        reply_markup=markup,
    )
    captured: list[TelegramMethod[Any]] = []

    async def next_request(
        bot: Bot, method: TelegramMethod[Any]
    ) -> Response[Any]:
        captured.append(method)
        return Response(ok=True, result=True)

    async def execute() -> None:
        await middleware(next_request, bot, request)

    asyncio.run(execute())

    sent = captured[0]
    assert isinstance(sent, SendMessage)
    assert sent.text == "The request failed. Dynamic plan title"
    assert isinstance(sent.reply_markup, InlineKeyboardMarkup)
    assert sent.reply_markup.inline_keyboard[0][0].text == "↩️ Back"
    assert request.text == "درخواست انجام نشد. Dynamic plan title"
    asyncio.run(bot.session.close())
