"""Native DRF fields for exact decimal integer monetary transport."""

import re
from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .money import MAX_MONEY_MINOR


@extend_schema_field(OpenApiTypes.STR)
class MoneyAmountField(serializers.Field[int, object, str, object]):
    """Reject fractional inputs and represent BIGINT safely as a decimal string."""

    default_error_messages = serializers.IntegerField.default_error_messages

    def __init__(
        self,
        *,
        min_value: int = -MAX_MONEY_MINOR,
        max_value: int = MAX_MONEY_MINOR,
        **kwargs: Any,
    ) -> None:
        self.integer = serializers.IntegerField(min_value=min_value, max_value=max_value)
        super().__init__(**kwargs)

    def to_internal_value(self, data: object) -> int:
        if not isinstance(data, int | str) or isinstance(data, bool):
            self.fail("invalid")
        if isinstance(data, str) and re.fullmatch(r"-?[0-9]+", data) is None:
            self.fail("invalid")
        amount = self.integer.to_internal_value(data)
        self.integer.run_validators(amount)
        return amount

    def to_representation(self, value: int) -> str:
        return str(value)
