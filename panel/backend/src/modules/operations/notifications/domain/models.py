from datetime import datetime

from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    BigIntField,
    BoolField,
    CharField,
    ForeignKeyField,
    IntField,
    JSONField,
    TextField,
    TimestampField,
)
from pydantic import JsonValue


class NotificationModel(PersistenceEntity):
    subscription_context: dict[str, JsonValue] | None = JSONField(default=None)
    customer_id: int = ForeignKeyField("tbl_customers.id", index=True)
    created_by_staff_id: int | None = ForeignKeyField(
        "tbl_staff.id", default=None
    )
    event_key: str = CharField(160)
    event_hash: str = CharField(64)
    kind: str = CharField(32)
    record_id: int | None = BigIntField(default=None)
    title: str = CharField(160)
    body: str = TextField()
    inbox_visible: bool = BoolField()
    is_read: bool = BoolField(default=False)
    status: str = CharField(32, index=True)
    revision: int = IntField(default=1)
    attempts: int = IntField(default=0)
    retry_budget_used: int = IntField(default=0)
    next_attempt_at: datetime | None = TimestampField(default=None, index=True)
    claim_token: str | None = CharField(64, default=None)
    lease_until: datetime | None = TimestampField(default=None)
    telegram_message_id: int | None = BigIntField(default=None)
    error_code: str | None = CharField(64, default=None)


class NotificationAttemptModel(PersistenceEntity):
    notification_id: int = ForeignKeyField("tbl_notifications.id", index=True)
    attempt: int = IntField()
    claim_token: str = CharField(64)
    outcome: str = CharField(32)
    error_code: str | None = CharField(64, default=None)
    finished_at: datetime | None = TimestampField(default=None)


class NotificationRecoveryModel(PersistenceEntity):
    notification_id: int = ForeignKeyField("tbl_notifications.id", index=True)
    revision: int = IntField()
    staff_id: int = ForeignKeyField("tbl_staff.id")
    action: str = CharField(16)
    previous_status: str = CharField(32)
    reason: str = CharField(250)
