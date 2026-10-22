"""Persistent service identity, provisioning work and subscription contracts."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from papilio_panel.shared.operations import OperationStatus


@dataclass(frozen=True)
class ServiceDefinition:
    name: str
    core_id: UUID
    inbound_id: UUID
    user_level: int | None = None
    identifier: UUID | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ServiceCreate:
    actor_id: int
    request_key: UUID
    definition: ServiceDefinition


@dataclass(frozen=True)
class ServiceRead:
    id: UUID
    owner_id: int
    core_id: UUID
    inbound_id: UUID
    name: str
    status: OperationStatus
    attempts: int
    error_code: str | None
    worker_pid: int | None
    lease_until: datetime | None


@dataclass(frozen=True)
class ServiceCreation:
    service: ServiceRead
    original_definition: ServiceDefinition
    created: bool


@dataclass(frozen=True)
class ServiceSearch:
    actor_id: int
    query: str = ""
    page: int = 1
    page_size: int = 20


@dataclass(frozen=True)
class ServicePage:
    items: tuple[ServiceRead, ...]
    count: int
    page: int
    page_size: int


@dataclass(frozen=True)
class XrayCredential:
    identifier: UUID = field(repr=False)
    email: str
    level: int


@dataclass(frozen=True)
class ServiceClaim:
    service: ServiceRead
    token: UUID | None


@dataclass(frozen=True)
class ServiceOutcome:
    retry_after_seconds: int | None = None


@dataclass(frozen=True)
class ServiceDelivery:
    service_id: UUID
    timeout_seconds: int


@dataclass(frozen=True)
class SubscriptionGrant:
    service_id: UUID
    nonce: UUID = field(repr=False)


@dataclass(frozen=True)
class SubscriptionLink:
    url: str = field(repr=False)


class ServiceTaskName(StrEnum):
    PROVISION = "papilio.services.provision"
    DISPATCH = "papilio.services.dispatch_outbox"
