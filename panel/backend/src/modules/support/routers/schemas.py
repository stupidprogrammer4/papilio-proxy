from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from src.modules.support.domain.dtos import (
    SupportPolicy,
    TicketCreate,
    TicketStatus,
)
from src.modules.support.domain.models import (
    SupportMessageModel,
    SupportStateChangeModel,
)


class SupportPolicyOut(SupportPolicy):
    capacity_valid: bool


class AdminTicketCreate(TicketCreate):
    customer_id: int = Field(gt=0)


class SupportDatedOut(BaseModel):
    id: int
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class SupportTicketOut(SupportDatedOut):
    updated_at: datetime
    customer_id: int
    subject: str
    status: TicketStatus
    revision: int
    subscription_id: int | None
    topup_id: int | None

    @field_validator("updated_at")
    @classmethod
    def updated_utc(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class SupportMessageOut(SupportDatedOut):
    revision: int
    body: str
    author_kind: Literal["staff", "customer"]

    @classmethod
    def from_model(cls, row: SupportMessageModel) -> "SupportMessageOut":
        assert row.created_at is not None
        return cls(
            id=row.id,
            created_at=row.created_at,
            revision=row.revision,
            body=row.body,
            author_kind="staff" if row.staff_id is not None else "customer",
        )


class SupportHistoryOut(SupportDatedOut):
    revision: int
    previous_status: TicketStatus
    status: TicketStatus
    reason: str
    author_kind: Literal["staff", "customer"]

    @classmethod
    def from_model(cls, row: SupportStateChangeModel) -> "SupportHistoryOut":
        assert row.created_at is not None
        return cls(
            id=row.id,
            created_at=row.created_at,
            revision=row.revision,
            previous_status=TicketStatus(row.previous_status),
            status=TicketStatus(row.status),
            reason=row.reason,
            author_kind="staff" if row.staff_id is not None else "customer",
        )


class AdminSupportMessageOut(SupportMessageOut):
    staff_id: int | None
    customer_id: int | None

    @classmethod
    def from_model(cls, row: SupportMessageModel) -> "AdminSupportMessageOut":
        return cls(
            **SupportMessageOut.from_model(row).model_dump(),
            staff_id=row.staff_id,
            customer_id=row.customer_id,
        )


class AdminSupportHistoryOut(SupportHistoryOut):
    staff_id: int | None
    customer_id: int | None

    @classmethod
    def from_model(
        cls, row: SupportStateChangeModel
    ) -> "AdminSupportHistoryOut":
        return cls(
            **SupportHistoryOut.from_model(row).model_dump(),
            staff_id=row.staff_id,
            customer_id=row.customer_id,
        )
