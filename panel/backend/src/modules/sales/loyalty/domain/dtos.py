from typing import Annotated, Literal

from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import Field


class CustomerTierWrite(BaseDTO):
    code: str = Field(min_length=2, max_length=32, pattern=r"^[a-z0-9_-]+$")
    title: str = Field(min_length=2, max_length=100)
    minimum_bytes: int = Field(ge=0, le=9223372036854775807)
    discount_bps: int = Field(ge=0, le=10000)
    is_enabled: bool
    expected_revision: int | None = Field(default=None, gt=0)


class LoyaltyPolicy(BaseDTO):
    enabled: bool
    tier_basis: Literal["net_purchases", "lifetime_purchases"]
    unlimited_credit_mode: Literal["exclude", "equivalent"]
    unlimited_equivalent_bytes: int = Field(ge=0, le=9223372036854775807)
    unlimited_plan_bytes: dict[
        Annotated[int, Field(gt=0, le=9223372036854775807)],
        Annotated[int, Field(ge=0, le=9223372036854775807)],
    ]
    first_purchase_basis: Literal["net_purchases", "lifetime_purchases"]
    first_purchase_discount_bps: int = Field(ge=0, le=10000)
    combination_mode: Literal["best", "additive", "sequential"]
    maximum_discount_bps: int = Field(ge=0, le=10000)
    minimum_qualifying_rial: int = Field(ge=0, le=9223372036854775807)
    renewal_tier_discount: bool
    notify_tier_changes: bool
    notify_discounts: bool


class LoyaltyPolicyWrite(BaseDTO):
    values: LoyaltyPolicy
    expected_revision: int = Field(gt=0)


class LoyaltySearch(BaseQuery):
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)
