from dataclasses import dataclass

from pydantic import BaseModel

from src.modules.network.configurations.domain.models import (
    ConfigurationModel,
    ProfileModel,
)


@dataclass(frozen=True, slots=True)
class ProfileUsageAssignment:
    profile: ProfileModel
    configuration: ConfigurationModel


class UsageSummary(BaseModel):
    upload_bytes: int
    download_bytes: int
    total_bytes: int
    sample_count: int


@dataclass(frozen=True, slots=True)
class UsageGrantAllocationKey:
    profile_id: int
    generation: int
    request_key: str


@dataclass(frozen=True, slots=True)
class UsageEventIdentity:
    node_id: int
    event_id: str


@dataclass(frozen=True, slots=True)
class UsageGenerationKey:
    subscription_id: int
    generation: int


@dataclass(frozen=True, slots=True)
class UsageProfileGenerationKey:
    profile_id: int
    generation: int


@dataclass(frozen=True, slots=True)
class UsageReservationTotal:
    subscription_id: int
    generation: int
    allocated_bytes: int
