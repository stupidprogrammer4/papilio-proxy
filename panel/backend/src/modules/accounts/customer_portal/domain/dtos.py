from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import Field


class CustomerTopupCreate(BaseDTO):
    amount_rial: int = Field(gt=0)
    destination_id: int | None = Field(default=None, gt=0)
    request_key: str = Field(min_length=8, max_length=64)


class CustomerPurchase(BaseDTO):
    expected_price_rial: int = Field(ge=0)
    plan_id: int = Field(gt=0)
    auto_renew: bool
    purchase_key: str = Field(min_length=8, max_length=64)


class CustomerPage(BaseQuery):
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)
