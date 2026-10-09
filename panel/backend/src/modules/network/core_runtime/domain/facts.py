from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class RuntimeConfigurationFacts:
    id: int
    revision: int
    listen_port: int
    port_network: str
    protocol: str
    encrypted_settings: str


@dataclass(frozen=True, slots=True)
class RuntimeProfileFacts:
    id: int
    configuration_id: int
    encrypted_credentials: str
    client_address: str | None
    subscription_id: int
    generation: int
    quota_bytes: int | None
    used_bytes: int
    expires_at: datetime | None
    status: str
    services_enabled: bool
    request_state: str | None
    request_policy_json: str | None
    request_activated_at: datetime | None
    duration_days: int | None
    service_hold_pending: bool
    provision_action: str | None
    provision_payload: str | None
    quota_policy_json: str | None


@dataclass(frozen=True, slots=True)
class RuntimeSnapshotFacts:
    configurations: tuple[RuntimeConfigurationFacts, ...]
    profiles: tuple[RuntimeProfileFacts, ...]
