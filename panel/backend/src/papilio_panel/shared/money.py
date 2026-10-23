"""Exact monetary storage and unit data shared by commerce capabilities."""

from enum import StrEnum

MAX_MONEY_MINOR = 9223372036854775807


class Currency(StrEnum):
    IRR = "IRR"


class MoneyUnit(StrEnum):
    RIAL = "rial"
