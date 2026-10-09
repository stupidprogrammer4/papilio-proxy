from papilio.infra.db.table import BaseTable
from sqlalchemy import Index, UniqueConstraint

from src.modules.operations.notifications.domain.models import (
    NotificationAttemptModel,
    NotificationModel,
    NotificationRecoveryModel,
)


class NotificationTable(NotificationModel, BaseTable, table=True):
    table_name = "tbl_notifications"
    __table_args__ = (
        Index("ix_notification_status_lease", "status", "lease_until"),
        UniqueConstraint(
            "customer_id", "event_key", name="uq_notification_event"
        ),
    )


class NotificationAttemptTable(
    NotificationAttemptModel, BaseTable, table=True
):
    table_name = "tbl_notification_attempts"
    __table_args__ = (
        UniqueConstraint(
            "notification_id", "attempt", name="uq_notification_attempt"
        ),
    )


class NotificationRecoveryTable(
    NotificationRecoveryModel, BaseTable, table=True
):
    table_name = "tbl_notification_recoveries"
    __table_args__ = (
        UniqueConstraint(
            "notification_id", "revision", name="uq_notification_recovery"
        ),
    )
