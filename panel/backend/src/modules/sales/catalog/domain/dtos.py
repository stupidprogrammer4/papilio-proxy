from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import Field, model_validator

from src.modules.network.ip_limits.domain.dtos import IpLimitChoice
from src.modules.sales.catalog.domain.policies import (
    FulfillmentPolicy,
    QuotaPolicy,
)


class PlanCreate(BaseDTO):
    quota_policy: QuotaPolicy | None = None
    fulfillment: FulfillmentPolicy | None = None
    ip_limit: IpLimitChoice | None = None
    group_id: int | None = Field(default=None, gt=0)
    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=100)
    quota_bytes: int | None = Field(default=None, gt=0)
    duration_days: int | None = Field(default=None, gt=0)
    price_rial: int = Field(ge=0)
    sort_order: int = 0

    @model_validator(mode="after")
    def require_limit(self) -> "PlanCreate":
        if self.quota_bytes is None and self.duration_days is None:
            raise ValueError("پلن باید محدودیت حجم یا مدت داشته باشد.")
        return self


class PlanUpdate(BaseDTO):
    quota_policy: QuotaPolicy | None = None
    fulfillment: FulfillmentPolicy | None = None
    ip_limit: IpLimitChoice | None = None
    group_id: int | None = Field(default=None, gt=0)
    title: str | None = Field(default=None, min_length=1, max_length=100)
    quota_bytes: int | None = Field(default=None, gt=0)
    duration_days: int | None = Field(default=None, gt=0)
    price_rial: int | None = Field(default=None, ge=0)
    sort_order: int | None = None

    @model_validator(mode="after")
    def require_change(self) -> "PlanUpdate":
        if not self.model_fields_set:
            raise ValueError("دست‌کم یک تغییر لازم است.")
        return self


class PlanSetActive(BaseDTO):
    is_active: bool


class PlanSearch(BaseQuery):
    q: str | None = Field(default=None, max_length=100)
    active: bool | None = None
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)
