from typing import Literal, cast

BotLocale = Literal["fa", "en", "ru", "zh"]
_SUPPORTED_LOCALES = {"fa", "en", "ru", "zh"}


def telegram_locale(language_code: str | None) -> BotLocale:
    language = (language_code or "").split("-", maxsplit=1)[0].lower()
    if language in _SUPPORTED_LOCALES:
        return cast(BotLocale, language)
    return "fa"
