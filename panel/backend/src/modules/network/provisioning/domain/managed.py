"""Verified managed application facts consumed by provisioning."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ManagedApplicationEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)
    subscription_id: int = Field(gt=0)
    node_id: int = Field(gt=0)
    core_id: int = Field(gt=0)
    profile_id: int = Field(gt=0)
    generation: int = Field(ge=0)
    configuration_id: int = Field(gt=0)
    configuration_revision: int = Field(gt=0)
    installed_revision_id: int = Field(gt=0)
    membership_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    claim_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    admission_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    observed_at: datetime


class ManagedRevocationEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)
    subscription_id: int = Field(gt=0)
    request_id: int = Field(gt=0)
    node_id: int = Field(gt=0)
    core_id: int = Field(gt=0)
    profile_id: int = Field(gt=0)
    generation: int = Field(ge=0)
    configuration_id: int = Field(gt=0)
    configuration_revision: int = Field(gt=0)
    installed_revision_id: int = Field(gt=0)
    membership_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    revocation_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    observed_at: datetime
