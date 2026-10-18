import asyncio
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import ValidationError

from src.modules.bot.app.queries.presentation import BotPresentationQuery
from src.modules.operations.preferences.domain.dtos import (
    BotLocaleTextSettings,
    BotPresentationSettings,
)
from src.modules.operations.preferences.interfaces import IPreferencesService


def test_bot_presentation_defaults_preserve_current_menu_and_greeting() -> (
    None
):
    settings = BotPresentationSettings()

    assert settings.catalog_version == 2
    assert len(settings.message_catalog["fa"]) >= 250
    assert settings.localized_texts["fa"].welcome_message == (
        "سلام {display_name} 🌿\n"
        "به {brand_title} خوش آمدید.\n"
        "💰 موجودی کیف پول: {balance}"
    )
    assert settings.welcome_photo_url is None
    assert set(settings.localized_texts) == {"fa", "en", "ru", "zh"}
    assert settings.localized_texts["en"].welcome_message.startswith(
        "Hello {display_name}"
    )
    assert settings.localized_texts["ru"].catalog_button_label.endswith(
        "услугу"
    )
    assert all(
        (
            settings.show_purchases,
            settings.show_loyalty,
            settings.show_trials,
            settings.show_account,
            settings.show_catalog,
            settings.show_subscriptions,
            settings.show_wallet,
            settings.show_support,
        )
    )


def test_bot_presentation_accepts_https_photo_and_known_placeholders() -> None:
    settings = BotPresentationSettings(
        welcome_photo_url="https://cdn.example.test/bot.webp",
        show_trials=False,
        localized_texts={
            "fa": BotLocaleTextSettings(
                welcome_message=(
                    "سلام {display_name}؛ {brand_title} · {balance}"
                ),
                catalog_button_label="خرید اختصاصی",
            )
        },
    )

    assert settings.welcome_photo_url == "https://cdn.example.test/bot.webp"
    assert (
        settings.localized_texts["fa"].catalog_button_label == "خرید اختصاصی"
    )
    assert not settings.show_trials


def test_bot_presentation_migrates_legacy_persian_values() -> None:
    settings = BotPresentationSettings.model_validate(
        {
            "welcome_message": "خوش آمدید {display_name}",
            "catalog_button_label": "فروشگاه تازه",
        }
    )

    assert (
        settings.localized_texts["fa"].welcome_message
        == "خوش آمدید {display_name}"
    )
    assert (
        settings.localized_texts["fa"].catalog_button_label == "فروشگاه تازه"
    )
    assert settings.catalog_version == 2
    assert settings.message_catalog["en"]["پلن دریافت نشد."] == ""


def test_presentation_query_reads_current_preferences() -> None:
    settings = BotPresentationSettings(show_trials=False)
    settings.message_catalog["en"]["پلن دریافت نشد."] = "Plan not found."

    class Preferences:
        async def current(self):
            return SimpleNamespace(
                values=SimpleNamespace(bot_presentation=settings)
            )

    query = BotPresentationQuery(cast(IPreferencesService, Preferences()))
    presentation = asyncio.run(query.get("fa"))

    trial = next(
        button
        for button in presentation.menu_buttons
        if button.action == "trial"
    )
    assert trial.visible is False
    assert (
        presentation.welcome_message
        == settings.localized_texts["fa"].welcome_message
    )
    assert (
        presentation.message_catalog["پلن دریافت نشد."]
        == (settings.message_catalog["fa"]["پلن دریافت نشد."])
    )
    english = asyncio.run(query.get("en"))
    assert english.welcome_message.startswith("Hello {display_name}")
    assert english.message_catalog["پلن دریافت نشد."] == "Plan not found."
    assert (
        next(
            button
            for button in english.menu_buttons
            if button.action == "catalog"
        ).label
        == "🛍 Buy a service"
    )

    settings.show_trials = True
    refreshed = asyncio.run(query.get("fa"))
    refreshed_trial = next(
        button for button in refreshed.menu_buttons if button.action == "trial"
    )
    assert refreshed_trial.visible is True


@pytest.mark.parametrize(
    "payload",
    [
        {"catalog_version": 3},
        {"localized_texts": {"en": {"welcome_message": "Hi {unknown}"}}},
        {"welcome_photo_url": "http://cdn.example.test/bot.jpg"},
        {"welcome_photo_url": "https://user:pass@cdn.example.test/bot.jpg"},
        {"welcome_photo_url": "https://127.0.0.1/bot.jpg"},
        {"welcome_photo_url": "https://cdn.example.test:bad/bot.jpg"},
        {"localized_texts": {"en": {"catalog_button_label": "x" * 65}}},
        {"message_catalog": {"fa": {"unknown key": "x"}}},
    ],
)
def test_bot_presentation_rejects_unsafe_or_unrenderable_values(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        BotPresentationSettings.model_validate(payload)
