from papilio.infra.db.table import BaseTable
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlmodel import Field

from src.modules.network.core_runtime.domain.models import (
    CoreRuntimeCommandModel,
    CoreRuntimeRevisionModel,
    CoreRuntimeStateModel,
)


class CoreRuntimeStateTable(CoreRuntimeStateModel, BaseTable, table=True):
    pass


class CoreRuntimeRevisionTable(
    CoreRuntimeRevisionModel, BaseTable, table=True
):
    encrypted_payload: str = Field(sa_type=LONGTEXT())
    encrypted_memberships: str | None = Field(default=None, sa_type=LONGTEXT())
    encrypted_usage: str | None = Field(default=None, sa_type=LONGTEXT())


class CoreRuntimeCommandTable(CoreRuntimeCommandModel, BaseTable, table=True):
    __table_args__ = (
        UniqueConstraint(
            "core_id", "request_key", name="uq_core_runtime_request"
        ),
    )
