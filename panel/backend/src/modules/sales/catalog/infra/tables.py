from papilio.infra.db.table import BaseTable

from src.modules.sales.catalog.domain.models import PlanModel


class PlanTable(PlanModel, BaseTable, table=True):
    pass
