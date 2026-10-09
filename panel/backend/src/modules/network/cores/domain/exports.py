from typing import Literal

from papilio.schemas.inputs import BaseDTO
from pydantic import BaseModel, Field


class CoreExportCapacity(BaseModel):
    enabled: bool
    max_configurations: int = Field(gt=0)
    max_profiles: int = Field(gt=0)
    max_output_bytes: int = Field(gt=0)


class CoreExportRequest(BaseDTO):
    mode: Literal["merged", "isolated"]


class CoreConfigurationRevision(BaseModel):
    configuration_id: int
    revision: int


class CoreArtifact(BaseModel):
    filename: str
    media_type: str
    content: str
    sha256: str
    configurations: list[CoreConfigurationRevision]


class CoreExport(BaseModel):
    core_id: int
    node_id: int
    kind: str
    mode: Literal["merged", "isolated"]
    application_status: Literal["not_applied"] = "not_applied"
    artifacts: list[CoreArtifact]
