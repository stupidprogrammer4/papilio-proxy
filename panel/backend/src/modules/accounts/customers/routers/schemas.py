from datetime import UTC, datetime

from pydantic import BaseModel, field_validator

from src.modules.accounts.customers.domain.dtos import CustomerAccessState
from src.modules.accounts.customers.domain.models import (
    CustomerAccessChangeModel,
    CustomerModel,
)


class CustomerOut(CustomerAccessState):
    id: int
    display_name: str
    telegram_id: int | None
    service_hold_pending: bool
    service_hold_clock: str | None

    @classmethod
    def from_model(cls, item: CustomerModel) -> "CustomerOut":
        return cls.model_validate(item, from_attributes=True)


class CustomerAccessChangeOut(BaseModel):
    id: int
    customer_id: int
    staff_id: int | None
    reseller_id: int | None
    actor_account_id: int | None
    created_at: datetime
    previous: CustomerAccessState
    values: CustomerAccessState
    reason: str
    clock: str | None

    @field_validator("created_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value

    @classmethod
    def from_model(
        cls, item: CustomerAccessChangeModel
    ) -> "CustomerAccessChangeOut":
        return cls(
            **item.model_dump(),
            previous=CustomerAccessState.model_validate_json(
                item.previous_json
            ),
            values=CustomerAccessState.model_validate_json(item.values_json),
        )
