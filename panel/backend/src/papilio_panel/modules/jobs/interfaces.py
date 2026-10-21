"""Typed asynchronous operation capability and infrastructure contracts."""

from typing import Protocol
from uuid import UUID

from .domain import (
    Delivery,
    ExecutionClaim,
    ExecutionOutcome,
    OperationCreation,
    OperationRead,
    ProbeKind,
    ProbeResult,
    ProbeSubmission,
    Readiness,
    ScheduleRead,
    ScheduleUpdate,
    SystemStatus,
    WorkerObservation,
)


class JobCapability(Protocol):
    def submit(self, values: ProbeSubmission) -> OperationRead: ...

    def read(self, operation_id: UUID, actor_id: int) -> OperationRead: ...

    def cancel(self, operation_id: UUID, actor_id: int) -> OperationRead: ...


class OperationStorage(Protocol):
    def create(self, values: ProbeSubmission) -> OperationCreation: ...

    def add_outbox(self, operation_id: UUID) -> None: ...

    def read(self, operation_id: UUID, actor_id: int) -> OperationRead: ...

    def cancel_queued(self, operation_id: UUID, actor_id: int) -> None: ...

    def claim(self, operation_id: UUID, kind: ProbeKind) -> ExecutionClaim: ...

    def finish(self, operation_id: UUID, token: UUID, result: ProbeResult) -> None: ...

    def reject(self, operation_id: UUID, token: UUID, error_code: str) -> None: ...

    def pending_deliveries(self) -> tuple[Delivery, ...]: ...

    def mark_dispatched(self, deliveries: tuple[Delivery, ...]) -> None: ...


class ProbeChecks(Protocol):
    def io(self) -> ProbeResult: ...

    def cpu(self) -> ProbeResult: ...


class ProbeExecutionCapability(Protocol):
    def execute(self, operation_id: UUID, kind: ProbeKind) -> ExecutionOutcome: ...


class DeliveryPublisher(Protocol):
    def publish(self, deliveries: tuple[Delivery, ...]) -> None: ...


class PublicationCapability(Protocol):
    def dispatch(self) -> None: ...


class ExecutionHealthStorage(Protocol):
    def readiness(self) -> Readiness: ...

    def observations(self) -> tuple[WorkerObservation, ...]: ...

    def record(self, role: str, actual_queue: str) -> None: ...


class ExecutionHealthCapability(Protocol):
    def readiness(self) -> Readiness: ...

    def status(self) -> SystemStatus: ...

    def record(self, role: str, actual_queue: str) -> None: ...


class ScheduleStorage(Protocol):
    def read_all(self) -> tuple[ScheduleRead, ...]: ...

    def update(self, values: ScheduleUpdate) -> ScheduleRead: ...


class ScheduleCapability(Protocol):
    def read_all(self, actor_id: int) -> tuple[ScheduleRead, ...]: ...

    def update(self, actor_id: int, values: ScheduleUpdate) -> ScheduleRead: ...
