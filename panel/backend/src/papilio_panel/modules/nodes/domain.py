"""Typed node identity, runtime configuration, credentials and work facts."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from papilio_panel.shared.operations import OperationStatus


@dataclass(frozen=True)
class AgentRuntime:
    listen_address: str = "0.0.0.0:9443"
    xray_api_address: str = "127.0.0.1:10085"
    request_timeout_seconds: int = 15
    read_header_timeout_seconds: int = 5
    idle_timeout_seconds: int = 60
    shutdown_timeout_seconds: int = 20
    max_body_bytes: int = 1048576
    max_grpc_reply_bytes: int = 16777216


@dataclass(frozen=True)
class CertificatePolicy:
    validity_seconds: int = 2592000
    authority_validity_seconds: int = 31536000
    backdate_seconds: int = 60


@dataclass(frozen=True)
class NodeDefaults:
    runtime: AgentRuntime = field(default_factory=AgentRuntime)
    certificate_policy: CertificatePolicy = field(default_factory=CertificatePolicy)


@dataclass(frozen=True)
class NodeDefinition:
    name: str
    endpoint_url: str
    runtime: AgentRuntime = field(default_factory=AgentRuntime)
    certificate_policy: CertificatePolicy = field(default_factory=CertificatePolicy)


@dataclass(frozen=True)
class NodeCreate:
    actor_id: int
    request_key: UUID
    definition: NodeDefinition


class NodeWorkKind(StrEnum):
    ISSUE = "issue_credentials"
    CHECK = "check_connection"


class NodeTaskName(StrEnum):
    ISSUE = "papilio.nodes.issue_credentials"
    CHECK = "papilio.nodes.check_connection"
    DISPATCH = "papilio.nodes.dispatch_outbox"


@dataclass(frozen=True)
class NodeRead:
    id: UUID
    deployment_id: UUID
    owner_id: int
    name: str
    endpoint_url: str
    runtime: AgentRuntime
    certificate_policy: CertificatePolicy
    credentials_ready: bool
    certificate_expires_at: datetime | None
    last_reachable: bool | None
    last_checked_at: datetime | None
    last_error_code: str | None
    uptime_seconds: int | None
    last_operation_id: UUID | None


@dataclass(frozen=True)
class NodeWorkRead:
    id: UUID
    node_id: UUID
    actor_id: int
    kind: NodeWorkKind
    status: OperationStatus
    attempts: int
    error_code: str | None
    worker_pid: int | None
    lease_until: datetime | None


@dataclass(frozen=True)
class NodeCreation:
    node: NodeRead
    operation: NodeWorkRead
    created: bool
    original_definition: NodeDefinition


@dataclass(frozen=True)
class WorkSubmission:
    actor_id: int
    node_id: UUID
    request_key: UUID
    kind: NodeWorkKind


@dataclass(frozen=True)
class WorkCreation:
    operation: NodeWorkRead
    created: bool


@dataclass(frozen=True)
class NodeSearch:
    actor_id: int
    query: str = ""
    page: int = 1
    page_size: int = 20


@dataclass(frozen=True)
class NodePage:
    items: tuple[NodeRead, ...]
    count: int
    page: int
    page_size: int


@dataclass(frozen=True)
class WorkClaim:
    operation: NodeWorkRead
    node: NodeRead
    token: UUID | None


@dataclass(frozen=True)
class WorkOutcome:
    retry_after_seconds: int | None = None


@dataclass(frozen=True)
class WorkDelivery:
    operation_id: UUID
    kind: NodeWorkKind
    timeout_seconds: int


@dataclass(frozen=True)
class CertificateInput:
    node_id: UUID
    deployment_id: UUID
    hostname: str
    policy: CertificatePolicy


@dataclass(frozen=True)
class CredentialPrivateKeys:
    authority: str = field(repr=False)
    server: str = field(repr=False)
    control: str = field(repr=False)


@dataclass(frozen=True)
class IssuedCredentials:
    authority_certificate: str
    server_certificate: str
    control_certificate: str
    private_keys: CredentialPrivateKeys = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True)
class NodeConnection:
    node_id: UUID
    deployment_id: UUID
    endpoint_url: str
    runtime: AgentRuntime
    credentials: IssuedCredentials = field(repr=False)


@dataclass(frozen=True)
class ProbeObservation:
    reachable: bool
    uptime_seconds: int | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class NodeProbe:
    actor_id: int
    node_id: UUID


@dataclass(frozen=True)
class XrayUserIdentity:
    inbound_tag: str
    email: str


@dataclass(frozen=True)
class VlessUser:
    identity: XrayUserIdentity
    identifier: UUID = field(repr=False)
    flow: str = ""
    level: int = 0


@dataclass(frozen=True)
class XrayApply:
    actor_id: int
    node_id: UUID
    user: VlessUser


@dataclass(frozen=True)
class XrayRemove:
    actor_id: int
    node_id: UUID
    identity: XrayUserIdentity


@dataclass(frozen=True)
class MutationObservation:
    node_id: UUID
    succeeded: bool
    changed: bool | None = None
    error_code: str | None = None
