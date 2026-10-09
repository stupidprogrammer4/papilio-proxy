from datetime import datetime
from typing import Literal

from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import BaseModel, Field


class ServerJsonCapacity(BaseModel):
    enabled: bool
    max_document_bytes: int = Field(gt=0)
    max_depth: int = Field(gt=0)


class ServerJsonDocument(BaseModel):
    mode: Literal["managed", "experimental"]
    source: str


class ServerJsonUpdate(BaseDTO):
    expected_revision: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=250)
    document: ServerJsonDocument | None


class ServerJsonRestore(BaseDTO):
    expected_revision: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=250)


class ServerJsonState(BaseModel):
    configuration_id: int
    revision: int
    core_kind: str
    supported: bool
    capacity: ServerJsonCapacity | None
    document: ServerJsonDocument | None


class ServerJsonHistorySearch(BaseQuery):
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class ServerJsonRevision(BaseModel):
    id: int
    revision: int
    staff_id: int
    reason: str
    created_at: datetime
    document: ServerJsonDocument | None
