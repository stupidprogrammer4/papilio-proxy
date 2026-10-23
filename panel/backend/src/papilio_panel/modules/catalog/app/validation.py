"""Pure validation of supported service product terms."""

from papilio_panel.shared.errors import InvalidInput
from papilio_panel.shared.money import MAX_MONEY_MINOR, Currency

from ..domain import ProductDefinition


def definition(values: ProductDefinition) -> None:
    if not values.name.strip() or values.name != values.name.strip() or len(values.name) > 80:
        raise InvalidInput("Enter a product name without surrounding whitespace.")
    if values.currency != Currency.IRR:
        raise InvalidInput("This release supports IRR products priced in rials.")
    if type(values.price_minor) is not int or not 0 <= values.price_minor <= MAX_MONEY_MINOR:
        raise InvalidInput("Enter a nonnegative integer price within signed BIGINT.")
    if values.user_level is not None and (
        type(values.user_level) is not int or not 0 <= values.user_level <= 4294967295
    ):
        raise InvalidInput("Choose an Xray user level within uint32.")
    if type(values.is_active) is not bool:
        raise InvalidInput("Choose whether this product is active.")
