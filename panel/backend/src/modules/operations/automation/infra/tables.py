from papilio.infra.db.table import BaseTable
from sqlalchemy import UniqueConstraint

from src.modules.operations.automation.domain.models import (
    AutomationRegistrationModel,
    AutomationRevisionModel,
)


class AutomationRegistrationTable(
    AutomationRegistrationModel, BaseTable, table=True
):
    pass


class AutomationRevisionTable(AutomationRevisionModel, BaseTable, table=True):
    __table_args__ = (
        UniqueConstraint("key", "revision", name="uq_automation_key_revision"),
    )
