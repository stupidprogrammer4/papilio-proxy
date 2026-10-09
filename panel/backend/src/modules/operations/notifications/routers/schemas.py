from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator

from src.modules.operations.notifications.domain.context import (
    SubscriptionNoticeContext,
)
from src.modules.operations.notifications.domain.dtos import (
    DeliveryStatus,
    ManualNotificationCreate,
    NotificationKind,
    NotificationPolicy,
)


class NotificationPolicyOut(NotificationPolicy):
    supported_kinds: list[NotificationKind]
    capacity_valid: bool
    outbound_available: bool


class AdminNotificationCreate(ManualNotificationCreate):
    customer_id: int = Field(gt=0)


class NotificationDatedOut(BaseModel):
    id: int
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class NotificationOut(NotificationDatedOut):
    subscription_context: SubscriptionNoticeContext | None = None
    kind: NotificationKind
    record_id: int | None
    title: str
    body: str
    is_read: bool


class AdminNotificationOut(NotificationOut):
    created_by_staff_id: int | None
    customer_id: int
    inbox_visible: bool
    status: DeliveryStatus
    revision: int
    attempts: int
    retry_budget_used: int
    next_attempt_at: datetime | None
    telegram_message_id: int | None
    error_code: str | None

    @field_validator("next_attempt_at")
    @classmethod
    def next_utc(cls, value: datetime | None) -> datetime | None:
        return (
            value.replace(tzinfo=UTC)
            if value is not None and value.tzinfo is None
            else value
        )


class NotificationAttemptOut(NotificationDatedOut):
    attempt: int
    outcome: str
    error_code: str | None
    finished_at: datetime | None

    @field_validator("finished_at")
    @classmethod
    def finished_utc(cls, value: datetime | None) -> datetime | None:
        return (
            value.replace(tzinfo=UTC)
            if value is not None and value.tzinfo is None
            else value
        )


class NotificationRecoveryOut(NotificationDatedOut):
    revision: int
    staff_id: int
    action: str
    previous_status: str
    reason: str


class NotificationQueuedOut(BaseModel):
    notification_id: int
