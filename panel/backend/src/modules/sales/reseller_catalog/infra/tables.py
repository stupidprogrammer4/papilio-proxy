from papilio.infra.db.table import BaseTable
from sqlalchemy import UniqueConstraint

from src.modules.sales.reseller_catalog.domain.models import (
    ResellerPlanChangeModel,
    ResellerPlanModel,
)


class ResellerPlanTable(ResellerPlanModel, BaseTable, table=True):
    __table_args__ = (UniqueConstraint("reseller_id", "plan_id"),)


class ResellerPlanChangeTable(ResellerPlanChangeModel, BaseTable, table=True):
    pass
