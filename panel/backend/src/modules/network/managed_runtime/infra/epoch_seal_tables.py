from datetime import datetime

from papilio.infra.db.table import BaseTable
from sqlalchemy import Column
from sqlalchemy.dialects.mysql import DATETIME, LONGTEXT
from sqlmodel import Field

from src.modules.network.managed_runtime.domain.epoch_seal_models import (
    ManagedEpochSealModel,
)


class ManagedEpochSealTable(ManagedEpochSealModel, BaseTable, table=True):
    accepted_at: datetime = Field(
        sa_column=Column(DATETIME(fsp=6), nullable=False)
    )
    encrypted_receipt: str = Field(sa_type=LONGTEXT)
