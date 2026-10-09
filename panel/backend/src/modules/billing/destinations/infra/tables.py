from papilio.infra.db.table import BaseTable

from src.modules.billing.destinations.domain.models import (
    PaymentDestinationModel,
)


class PaymentDestinationTable(PaymentDestinationModel, BaseTable, table=True):
    pass
