"""Typed owner inspection and explicit recovery inputs, writes and audit results."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from .domain import MessageRead, MessageState, RecoveryAction, WorkState


@dataclass(frozen=True)
class InspectionWindow:
    actor_id: int
    bot_id: UUID
    query: str = ""
    page: int = 1
    page_size: int = 20


@dataclass(frozen=True)
class WorkSearch(InspectionWindow):
    status: WorkState | None = None


@dataclass(frozen=True)
class MessageSearch(InspectionWindow):
    status: MessageState | None = None


@dataclass(frozen=True)
class WorkInspection:
    id: UUID
    event_id: int
    bot_id: UUID
    status: WorkState
    revision: int
    attempts: int
    error_code: str | None
    retry_at: datetime | None
    lease_until: datetime | None
    received_at: datetime
    completed_at: datetime | None
    actions: tuple[RecoveryAction, ...] = ()


@dataclass(frozen=True)
class WorkPage:
    items: tuple[WorkInspection, ...]
    count: int
    page: int
    page_size: int


@dataclass(frozen=True)
class MessagePage:
    items: tuple[MessageRead, ...]
    count: int
    page: int
    page_size: int


@dataclass(frozen=True)
class RecoveryDefinition:
    request_key: UUID
    expected_revision: int
    action: RecoveryAction
    note: str = ""


@dataclass(frozen=True)
class WorkRecoveryInput:
    actor_id: int
    bot_id: UUID
    work_id: UUID
    definition: RecoveryDefinition


@dataclass(frozen=True)
class MessageRecoveryInput:
    actor_id: int
    bot_id: UUID
    message_id: UUID
    definition: RecoveryDefinition


@dataclass(frozen=True)
class RecoveryAudit:
    id: UUID
    actor_id: int
    bot_id: UUID
    request_key: UUID
    expected_revision: int
    action: RecoveryAction
    note: str
    previous_status: str
    previous_attempts: int
    created_at: datetime


@dataclass(frozen=True)
class WorkRecoveryRead(RecoveryAudit):
    work_id: UUID


@dataclass(frozen=True)
class MessageRecoveryRead(RecoveryAudit):
    message_id: UUID


@dataclass(frozen=True)
class WorkRecoveryPage:
    items: tuple[WorkRecoveryRead, ...]
    count: int
    page: int
    page_size: int


@dataclass(frozen=True)
class MessageRecoveryPage:
    items: tuple[MessageRecoveryRead, ...]
    count: int
    page: int
    page_size: int


@dataclass(frozen=True)
class WorkRecoveryWrite:
    values: WorkRecoveryInput
    previous: WorkInspection
    status: WorkState
    attempts: int
    completed_at: datetime | None
    error_code: str | None


@dataclass(frozen=True)
class MessageRecoveryWrite:
    values: MessageRecoveryInput
    previous: MessageRead
    status: MessageState
    attempts: int
    error_code: str | None


@dataclass(frozen=True)
class WorkRecoveryReservation:
    recovery: WorkRecoveryRead
    created: bool


@dataclass(frozen=True)
class MessageRecoveryReservation:
    recovery: MessageRecoveryRead
    created: bool


@dataclass(frozen=True)
class WorkRecoveryResult:
    recovery: WorkRecoveryRead
    work: WorkInspection
    created: bool


@dataclass(frozen=True)
class MessageRecoveryResult:
    recovery: MessageRecoveryRead
    message: MessageRead
    created: bool
