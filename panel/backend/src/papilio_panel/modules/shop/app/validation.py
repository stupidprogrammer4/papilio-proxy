"""Pure supported shop policy and plain-text template validation."""

from dataclasses import fields
from string import Template
from urllib.parse import urlsplit

from papilio_panel.shared.errors import InvalidInput
from papilio_panel.shared.money import MAX_MONEY_MINOR

from ..domain import DEFAULT_TEXTS, SHOP_LOCALES, ShopDefinition, ShopTextCatalog, ShopTextContext


def definition(values: ShopDefinition, max_page_size: int) -> None:
    origin = urlsplit(values.public_origin)
    if (
        origin.scheme not in {"http", "https"}
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.query
        or origin.fragment
        or origin.path not in {"", "/"}
    ):
        raise InvalidInput(
            "Choose an HTTP or HTTPS panel origin without credentials, path or query."
        )
    if (
        values.locale not in DEFAULT_TEXTS
        or type(values.enabled) is not bool
        or type(values.delivery_enabled) is not bool
    ):
        raise InvalidInput("Choose a supported locale and explicit shop/delivery availability.")
    if type(values.page_size) is not int or not 1 <= values.page_size <= max_page_size:
        raise InvalidInput("Choose a supported catalogue page size.")
    numbers = (
        values.retry_seconds,
        values.lease_seconds,
        values.max_attempts,
        values.confirmation_ttl_seconds,
    )
    if any(type(number) is not int or not 1 <= number <= 2147483647 for number in numbers):
        raise InvalidInput("Timing and retry values must fit positive PostgreSQL integers.")
    if values.ambiguous_delivery not in {"hold", "retry"}:
        raise InvalidInput("Choose hold or retry for an uncertain Telegram send.")
    texts(values.texts)


def texts(values: ShopTextCatalog) -> None:
    if set(values) != set(SHOP_LOCALES):
        raise InvalidInput("Provide the complete supported shop text catalogues.")
    allowed = {item.name for item in fields(ShopTextContext)}
    for locale in SHOP_LOCALES:
        messages = values[locale]
        if set(messages) != set(DEFAULT_TEXTS[locale]):
            raise InvalidInput("Provide every supported shop message and button label.")
        for value in messages.values():
            template = Template(value)
            if (
                not value.strip()
                or len(value.encode("utf-16-le")) > 8192
                or not template.is_valid()
                or not set(template.get_identifiers()) <= allowed
            ):
                raise InvalidInput(
                    "Use nonempty plain-text templates within Telegram's message limit "
                    "and supported placeholders."
                )


def revision(value: int) -> None:
    if type(value) is not int or not 1 <= value < MAX_MONEY_MINOR:
        raise InvalidInput("Choose a positive shop configuration revision within signed BIGINT.")
