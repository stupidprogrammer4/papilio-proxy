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
