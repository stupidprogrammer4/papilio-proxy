"""Verified managed application facts consumed by provisioning."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class ManagedApplicationBatchItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    task_id: int = Field(gt=0)
    evidence: ManagedApplicationEvidence


class ManagedApplicationBatch(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: tuple[ManagedApplicationBatchItem, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_tasks(self) -> "ManagedApplicationBatch":
        task_ids = [item.task_id for item in self.items]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Each provision task may appear once.")
        return self


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
