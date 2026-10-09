from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CoreUsageCapacity(BaseModel):
    mode: Literal["disabled", "observe", "polled_stop"]
    stats_ports: dict[int, int] = Field(default_factory=dict)
    max_profiles: int = Field(gt=0)
    max_document_bytes: int = Field(gt=0)
    observation_seconds: int = Field(gt=0)
    max_node_endpoints: int = Field(default=10000, gt=0)
    max_peer_usage_bytes: int = Field(default=20000000, gt=0)
    max_open_usage_grants: int = Field(default=10000, gt=0)

    @model_validator(mode="after")
    def valid_ports(self) -> "CoreUsageCapacity":
        if any(
            core <= 0 or not 1 <= port <= 65535
            for core, port in self.stats_ports.items()
        ):
            raise ValueError(
                "Stats ports require positive core IDs and valid ports"
            )
        return self


class RuntimeUsageArtifact(BaseModel):
    artifact_filename: str
    artifact_sha256: str
    listen_address: Literal["127.0.0.1"]
    listen_port: int
    inbound_api_tag: Literal["papilio-stats-api"]
    protected_ports: list[int]


class RuntimeUsageProfile(BaseModel):
    profile_id: int
    subscription_id: int
    generation: int
    configuration_id: int
    configuration_revision: int
    artifact_filename: str
    artifact_sha256: str
    counter_identity: str
    grant_bytes: int


class RuntimeUsageSnapshot(BaseModel):
    mode: Literal["observe", "polled_stop"]
    artifacts: list[RuntimeUsageArtifact]
    profiles: list[RuntimeUsageProfile]


class RuntimeUsageCapability(BaseModel):
    mode: Literal["disabled", "observe", "polled_stop"]
    configured_port: int | None
    available: bool
    reason_code: str | None
    protected_ports: list[int]


class RuntimeUsageObservation(BaseModel):
    runtime_revision_id: int = Field(gt=0)
    usage_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    membership_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    process_epoch: str = Field(pattern=r"^[a-zA-Z0-9_-]{32,128}$")
    observed_status: Literal["running", "stopped"]
