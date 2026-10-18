from src.modules.bot.domain.dtos import BotLocale
from src.modules.bot.domain.results import BotMenuButton, BotPresentation
from src.modules.operations.preferences.domain.dtos import (
    BotPresentationSettings,
)


def presentation_from_settings(
    settings: BotPresentationSettings, locale: BotLocale
) -> BotPresentation:
    texts = settings.localized_texts[locale]
    menu_buttons = (
        BotMenuButton(
            "purchases",
            texts.purchases_button_label,
            settings.show_purchases,
        ),
        BotMenuButton(
            "loyalty", texts.loyalty_button_label, settings.show_loyalty
        ),
        BotMenuButton("trial", texts.trial_button_label, settings.show_trials),
        BotMenuButton(
            "account", texts.account_button_label, settings.show_account
        ),
        BotMenuButton(
            "catalog", texts.catalog_button_label, settings.show_catalog
        ),
        BotMenuButton(
            "subscriptions",
            texts.subscriptions_button_label,
            settings.show_subscriptions,
        ),
        BotMenuButton(
            "wallet", texts.wallet_button_label, settings.show_wallet
        ),
        BotMenuButton(
            "support", texts.support_button_label, settings.show_support
        ),
    )
    return BotPresentation(
        welcome_message=texts.welcome_message,
        welcome_photo_url=settings.welcome_photo_url,
        menu_buttons=menu_buttons,
        message_catalog=settings.message_catalog[locale],
    )
