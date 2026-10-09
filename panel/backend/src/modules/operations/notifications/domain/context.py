from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SubscriptionNoticeContext(BaseModel):
    subscription_id: int = Field(gt=0)
    generation: int = Field(ge=0)
    threshold_code: str = Field(min_length=1, max_length=64)
    quota_bytes: int | None = Field(default=None, ge=0)
    used_bytes: int = Field(ge=0)
    remaining_bytes: int | None = Field(default=None, ge=0)
    expires_at: datetime | None
    renewal_price_rial: int | None = Field(default=None, ge=0)
    captured_at: datetime

    @field_validator("expires_at", "captured_at")
    @classmethod
    def utc_date(cls, value: datetime | None) -> datetime | None:
        return (
            value.replace(tzinfo=UTC)
            if value is not None and value.tzinfo is None
            else value
        )


class SubscriptionNoticeAction(BaseModel):
    kind: Literal["subscription"] = "subscription"
    subscription_id: int = Field(gt=0)


class CheckoutNoticeAction(BaseModel):
    kind: Literal["checkout"] = "checkout"
    checkout_id: int = Field(gt=0)
