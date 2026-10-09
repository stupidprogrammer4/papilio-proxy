from papilio.infra.db.table import BaseTable

from src.modules.accounts.customer_auth.domain.models import (
    CustomerLoginModel,
    CustomerSessionModel,
)


class CustomerLoginTable(CustomerLoginModel, BaseTable, table=True):
    pass


class CustomerSessionTable(CustomerSessionModel, BaseTable, table=True):
    pass
