"""Native immutable audit projections for the two recovered resource types."""

from ..domain import RecoveryAction
from ..models import MessageRecovery, WorkRecovery
from ..recovery_contracts import MessageRecoveryRead, WorkRecoveryRead


def work_recovery_read(row: WorkRecovery) -> WorkRecoveryRead:
    return WorkRecoveryRead(
        row.id,
        row.actor_id,
        row.bot_id,
        row.request_key,
        row.expected_revision,
        RecoveryAction(row.action),
        row.note,
        row.previous_status,
        row.previous_attempts,
        row.created_at,
        row.work_id,
    )


def message_recovery_read(row: MessageRecovery) -> MessageRecoveryRead:
    return MessageRecoveryRead(
        row.id,
        row.actor_id,
        row.bot_id,
        row.request_key,
        row.expected_revision,
        RecoveryAction(row.action),
        row.note,
        row.previous_status,
        row.previous_attempts,
        row.created_at,
        row.message_id,
    )
