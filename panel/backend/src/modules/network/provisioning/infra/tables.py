from papilio.infra.db.table import BaseTable
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlmodel import Field

from src.modules.network.provisioning.domain.models import (
    ProvisionRequestModel,
    ProvisionTaskModel,
)


class ProvisionRequestTable(ProvisionRequestModel, BaseTable, table=True):
    __table_args__ = (
        UniqueConstraint(
            "subscription_id", "generation", name="uq_provision_generation"
        ),
    )


class ProvisionTaskTable(ProvisionTaskModel, BaseTable, table=True):
    encrypted_payload: str = Field(sa_type=LONGTEXT())
    __table_args__ = (
        UniqueConstraint(
            "request_id", "configuration_id", name="uq_provision_target"
        ),
    )
