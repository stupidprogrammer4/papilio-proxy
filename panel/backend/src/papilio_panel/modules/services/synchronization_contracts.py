"""Persistent native account synchronization policy, work and observation contracts."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from papilio_panel.shared.operations import OperationStatus

from .domain import ServiceRead

INITIAL_SYNCHRONIZATION_SECONDS = 60


class SynchronizationTaskName(StrEnum):
    SYNCHRONIZE = "papilio.services.synchronize"
    DISPATCH = "papilio.services.dispatch_synchronization"


@dataclass(frozen=True)
class SynchronizationRead:
    service_id: UUID
    enabled: bool
    interval_seconds: int
    revision: int
    generation: int
    status: OperationStatus
    attempts: int
    error_code: str | None
    worker_pid: int | None
    lease_until: datetime | None
    due_at: datetime
    last_completed_at: datetime | None


@dataclass(frozen=True)
class SynchronizationUpdate:
    actor_id: int
    service_id: UUID
    enabled: bool
    interval_seconds: int
    expected_revision: int


@dataclass(frozen=True)
class SynchronizationClaim:
    service: ServiceRead
    synchronization: SynchronizationRead
    token: UUID


@dataclass(frozen=True)
class SynchronizationDelivery:
    service_id: UUID
    generation: int
    timeout_seconds: int
