import asyncio

from papilio_telegram.api import BotApi
from papilio_telegram.commerce import BotPresentation
from papilio_telegram.config import BotApiLimits
from papilio_telegram.locales import telegram_locale


def test_telegram_locale_normalizes_supported_language_tags() -> None:
    assert telegram_locale("en-US") == "en"
    assert telegram_locale("RU") == "ru"
    assert telegram_locale("zh-hans") == "zh"


def test_telegram_locale_falls_back_to_persian() -> None:
    assert telegram_locale(None) == "fa"
    assert telegram_locale("de-DE") == "fa"


def test_presentation_state_is_isolated_between_concurrent_updates() -> None:
    api = BotApi(
        "https://panel.example.test",
        "controlled-key",
        5,
        BotApiLimits(65536, 4, 4096, 10, 10),
    )

    async def read_presentation(message: str) -> str:
        token = api._presentation.set(BotPresentation(welcome_message=message))
        await asyncio.sleep(0)
        result = api.presentation.welcome_message
        api._presentation.reset(token)
        return result

    async def read_both() -> tuple[str, str]:
        english_task = asyncio.create_task(read_presentation("English"))
        russian_task = asyncio.create_task(read_presentation("Русский"))
        english = await english_task
        russian = await russian_task
        return english, russian

    english, russian = asyncio.run(read_both())

    assert english == "English"
    assert russian == "Русский"
    assert api.presentation.welcome_message.startswith("سلام")
