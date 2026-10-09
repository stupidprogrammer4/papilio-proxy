from typing import Literal

from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import Field


class SubscriptionCreate(BaseDTO):
    expected_offer_sha256: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{64}$"
    )
    expected_price_rial: int | None = Field(default=None, ge=0)
    purchase_key: str = Field(min_length=8, max_length=128)
    customer_id: int = Field(gt=0)
    plan_id: int = Field(gt=0)
    auto_renew: bool = False


class AutoRenewChoice(BaseDTO):
    enabled: bool


class ProvisionFailure(BaseDTO):
    reason: str = Field(min_length=3, max_length=250)


class SubscriptionSearch(BaseQuery):
    customer_id: int | None = Field(default=None, gt=0)
    status: str | None = Field(default=None, max_length=32)
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class SubscriptionSuspend(BaseDTO):
    request_key: str = Field(min_length=8, max_length=64)
    reason: str = Field(min_length=3, max_length=250)
    clock: Literal["continue", "pause"]


class SubscriptionResume(BaseDTO):
    request_key: str = Field(min_length=8, max_length=64)
    reason: str = Field(min_length=3, max_length=250)


class SubscriptionControlSearch(BaseQuery):
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)
