"""Data contracts for durable execution and worker observations."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from papilio_panel.shared.operations import OperationStatus


class ProbeKind(StrEnum):
    IO = "io"
    CPU = "cpu"


@dataclass(frozen=True)
class ProbeSubmission:
    actor_id: int
    kind: ProbeKind
    request_key: UUID


@dataclass(frozen=True)
class ProbeResult:
    worker_pid: int
    worker_host: str
    database_ok: bool | None = None
    cache_ok: bool | None = None
    digest: str | None = None


@dataclass(frozen=True)
class OperationRead:
    id: UUID
    kind: ProbeKind
    status: OperationStatus
    created_at: datetime
    updated_at: datetime
    attempts: int
    result: ProbeResult | None
    error_code: str | None
    lease_until: datetime | None


@dataclass(frozen=True)
class OperationCreation:
    operation: OperationRead
    created: bool


@dataclass(frozen=True)
class ExecutionClaim:
    operation: OperationRead
    token: UUID | None
    actor_id: int


@dataclass(frozen=True)
class ExecutionOutcome:
    retry_after_seconds: int | None = None


@dataclass(frozen=True)
class Delivery:
    operation_id: UUID
    kind: ProbeKind


class TaskName(StrEnum):
    IO_PROBE = "papilio.jobs.io_probe"
    CPU_PROBE = "papilio.jobs.cpu_probe"
    DISPATCH = "papilio.jobs.dispatch"
    IO_HEARTBEAT = "papilio.jobs.io_heartbeat"
    CPU_HEARTBEAT = "papilio.jobs.cpu_heartbeat"


@dataclass(frozen=True)
class WorkerObservation:
    role: str
    queue: str
    worker_host: str
    worker_pid: int
    observed_at: datetime


@dataclass(frozen=True)
class Readiness:
    database: bool
    cache: bool
    workers: bool


@dataclass(frozen=True)
class SystemStatus:
    version: str
    brand_title: str
    environment: str
    instance: str
    database: bool
    cache: bool
    workers_ready: bool
    workers: tuple[WorkerObservation, ...]
    available_modules: tuple[str, ...]


class ScheduleKind(StrEnum):
    SHOP_OUTBOX = "shop-outbox"
    SERVICE_OUTBOX = "service-outbox"
    SERVICE_SYNCHRONIZATION = "service-synchronization"
    NODE_OUTBOX = "node-outbox"
    IO_HEARTBEAT = "io-heartbeat"
    CPU_HEARTBEAT = "cpu-heartbeat"
    OUTBOX = "outbox"


@dataclass(frozen=True)
class ScheduleRead:
    key: ScheduleKind
    enabled: bool
    interval_seconds: int
    changed_at: datetime


@dataclass(frozen=True)
class ScheduleUpdate:
    key: ScheduleKind
    enabled: bool
    interval_seconds: int
    expected_changed_at: datetime
