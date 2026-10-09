from typing import Literal

from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import Field, model_validator


class CustomerAccessState(BaseDTO):
    is_active: bool
    services_enabled: bool
    renewals_enabled: bool


class CustomerCreate(BaseDTO):
    access: CustomerAccessState | None = None
    display_name: str = Field(min_length=1, max_length=120)
    telegram_id: int | None = Field(default=None, gt=0)


class CustomerSearch(BaseQuery):
    q: str | None = Field(default=None, max_length=120)
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class CustomerProfileWrite(BaseDTO):
    display_name: str = Field(min_length=1, max_length=120)


class CustomerAccessWrite(BaseDTO):
    request_key: str = Field(min_length=8, max_length=64)
    expected: CustomerAccessState
    values: CustomerAccessState
    reason: str = Field(min_length=3, max_length=250)
    clock: Literal["continue", "pause"] | None

    @model_validator(mode="after")
    def explicit_clock(self) -> "CustomerAccessWrite":
        if (self.clock is None) != self.values.services_enabled:
            raise ValueError(
                "Disabled service access requires an explicit clock policy"
            )
        return self


class CustomerAccessSearch(BaseQuery):
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)
