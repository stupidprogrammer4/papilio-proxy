from papilio.infra.db.table import BaseTable

from src.modules.accounts.resellers.domain.models import (
    ResellerAccountChangeModel,
    ResellerAccountModel,
    ResellerChangeModel,
    ResellerCustomerModel,
    ResellerModel,
    ResellerSessionModel,
)


class ResellerTable(ResellerModel, BaseTable, table=True):
    pass


class ResellerAccountTable(ResellerAccountModel, BaseTable, table=True):
    pass


class ResellerSessionTable(ResellerSessionModel, BaseTable, table=True):
    pass


class ResellerCustomerTable(ResellerCustomerModel, BaseTable, table=True):
    pass


class ResellerChangeTable(ResellerChangeModel, BaseTable, table=True):
    pass


class ResellerAccountChangeTable(
    ResellerAccountChangeModel, BaseTable, table=True
):
    pass
