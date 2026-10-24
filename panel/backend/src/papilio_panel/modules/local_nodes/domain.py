"""Typed local runtime registration, delivery policy and operation facts."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from papilio_panel.modules.identity.domain import OwnerSetupInput
from papilio_panel.modules.nodes.domain import NodeDefinition, NodeRead
from papilio_panel.shared.operations import OperationStatus


@dataclass(frozen=True)
class LocalDefinition:
    node: NodeDefinition
    core_name: str
    inbound_tag: str
    public_host: str
    public_port: int
    default_user_level: int = 0
    bind_address: str = "0.0.0.0"
    bind_port: int = 8443


@dataclass(frozen=True)
class DeliveryPolicy:
    enabled: bool = True
    retry_interval_seconds: int = 1
    max_attempts: int = 5


@dataclass(frozen=True)
class DeliveryRead(DeliveryPolicy):
    revision: int = 1


@dataclass(frozen=True)
class LocalDefaults:
    available: bool
    definition: LocalDefinition
    delivery: DeliveryPolicy = field(default_factory=DeliveryPolicy)


@dataclass(frozen=True)
class LocalChoice:
    enabled: bool = True
    definition: LocalDefinition | None = None
    delivery: DeliveryPolicy = field(default_factory=DeliveryPolicy)


@dataclass(frozen=True)
class OwnerInitialization:
    owner: OwnerSetupInput
    local_node: LocalChoice | None = None


@dataclass(frozen=True)
class LocalCreate:
    actor_id: int
    request_key: UUID
    definition: LocalDefinition
    delivery: DeliveryPolicy = field(default_factory=DeliveryPolicy)


@dataclass(frozen=True)
class LocalBinding:
    values: LocalCreate
    node_id: UUID
    issue_operation_id: UUID
    core_id: UUID
    inbound_id: UUID
    timeout_seconds: int


@dataclass(frozen=True)
class LocalOperationRead:
    id: UUID
    request_key: UUID
    status: OperationStatus
    attempts: int
    error_code: str | None
    worker_pid: int | None
    due_at: datetime
    lease_until: datetime | None
    completed_at: datetime | None
    timeout_seconds: int


@dataclass(frozen=True)
class LocalRead:
    owner_id: int
    request_key: UUID
    node_id: UUID
    issue_operation_id: UUID
    core_id: UUID
    inbound_id: UUID
    definition: LocalDefinition
    initial_delivery: DeliveryPolicy
    delivery: DeliveryRead
    operation: LocalOperationRead


@dataclass(frozen=True)
class LocalCreation:
    record: LocalRead
    created: bool


@dataclass(frozen=True)
class DeliveryUpdate:
    actor_id: int
    policy: DeliveryPolicy
    expected_revision: int


@dataclass(frozen=True)
class LocalRetry:
    actor_id: int
    request_key: UUID


@dataclass(frozen=True)
class LocalBootstrap:
    operation_id: UUID
    node: NodeRead
    definition: LocalDefinition
    archive: bytes = field(repr=False)


@dataclass(frozen=True)
class LocalWork:
    record: LocalRead
    operation: LocalOperationRead


@dataclass(frozen=True)
class LocalClaim:
    work: LocalWork
    token: UUID


@dataclass(frozen=True)
class LocalAttempt:
    claim: LocalClaim | None = None
    retry_after_seconds: int | None = None


@dataclass(frozen=True)
class LocalDelivery:
    operation_id: UUID
    timeout_seconds: int
    attempts: int
    due_at: datetime


class LocalTaskName(StrEnum):
    PREPARE = "papilio.local_nodes.prepare"
    DISPATCH = "papilio.local_nodes.dispatch"
