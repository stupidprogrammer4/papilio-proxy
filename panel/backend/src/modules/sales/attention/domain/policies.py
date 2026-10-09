from typing import Literal

from papilio.schemas.inputs import BaseDTO
from pydantic import Field, model_validator


class LowQuotaThreshold(BaseDTO):
    code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    mode: Literal["any", "all"]
    remaining_percent_bps: int | None = Field(default=None, ge=0, le=10000)
    remaining_bytes: int | None = Field(
        default=None, ge=0, le=9223372036854775807
    )

    @model_validator(mode="after")
    def has_threshold(self) -> "LowQuotaThreshold":
        if self.remaining_percent_bps is None and self.remaining_bytes is None:
            raise ValueError("Select at least one remaining quota threshold")
        return self


class SubscriptionAlertPolicy(BaseDTO):
    enabled: bool
    low_quota: list[LowQuotaThreshold]
    expiry_hours: list[int]
    renewal_opportunity: bool

    @model_validator(mode="after")
    def unique_rules(self) -> "SubscriptionAlertPolicy":
        if len({rule.code for rule in self.low_quota}) != len(self.low_quota):
            raise ValueError("Quota rule codes must be distinct")
        if any(value <= 0 for value in self.expiry_hours) or len(
            set(self.expiry_hours)
        ) != len(self.expiry_hours):
            raise ValueError("Expiry hours must be distinct positive integers")
        return self
