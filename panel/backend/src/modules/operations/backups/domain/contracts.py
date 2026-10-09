from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class RecoverySettings(BaseModel):
    mysql_executable: str = Field(min_length=1)
    dump_executable: str = Field(min_length=1)
    command_timeout_seconds: int = Field(gt=0)
    io_chunk_bytes: int = Field(gt=0)
    max_sql_bytes: int = Field(gt=0)
    max_archive_bytes: int = Field(gt=0)
    max_payload_bytes: int = Field(gt=0)
    consistency: Literal["online", "locked"]
    temporary_directory: Path


class DatabaseSnapshot(BaseModel):
    sql: str
    schema_revision: str


class RecoveryPayload(BaseModel):
    format_version: Literal[1]
    created_at: datetime
    source_database: str
    consistency: Literal["online", "locked"]
    schema_revision: str
    config_yaml: str
    sql_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sql: str


class RestoreResult(BaseModel):
    schema_revision: str
    table_count: int
