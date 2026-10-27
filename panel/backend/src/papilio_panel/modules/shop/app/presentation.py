"""Pure plaintext shop replies with native Telegram callback identities."""

from dataclasses import asdict
from string import Template

from papilio_panel.modules.bots.domain import TelegramButton, TelegramReply
from papilio_panel.shared.errors import InvalidInput

from ..domain import ShopDefinition, ShopTextContext

EMPTY_TEXT_CONTEXT = ShopTextContext()


def render(
    settings: ShopDefinition, key: str, context: ShopTextContext = EMPTY_TEXT_CONTEXT
) -> str:
    text = Template(settings.texts[settings.locale][key]).substitute(asdict(context))
    if not text.strip() or len(text.encode("utf-16-le")) > 8192:
        raise InvalidInput("The configured shop reply exceeds Telegram's text limit.")
    return text


def menu(settings: ShopDefinition) -> tuple[TelegramButton, ...]:
    buttons = []
    if settings.flows.catalogue:
        buttons.append(TelegramButton(render(settings, "products_button"), "catalogue:1"))
    if settings.flows.wallet:
        buttons.append(TelegramButton(render(settings, "wallet_button"), "wallet"))
    if settings.flows.orders:
        buttons.append(TelegramButton(render(settings, "orders_button"), "orders:1"))
    if settings.flows.help:
        buttons.append(TelegramButton(render(settings, "help_button"), "help"))
    return tuple(buttons)


def reply(
    settings: ShopDefinition, key: str, context: ShopTextContext = EMPTY_TEXT_CONTEXT
) -> TelegramReply:
    return TelegramReply(render(settings, key, context), menu(settings))


def welcome(settings: ShopDefinition, context: ShopTextContext) -> TelegramReply:
    text = render(settings, "welcome", context)
    if settings.welcome_photo_url is not None and len(text) > 1024:
        raise InvalidInput("The configured welcome exceeds Telegram's photo-caption limit.")
    return TelegramReply(text, menu(settings), settings.welcome_photo_url)
