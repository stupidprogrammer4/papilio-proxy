from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)

from src.modules.billing.payment_identifiers.domain.models import (
    PaymentAmountReservationModel,
)
from src.modules.billing.payment_identifiers.infra.tables import (
    PaymentAmountReservationTable,
)


class PaymentAmountReservationRepository(
    MySQLPersistenceRepository[PaymentAmountReservationModel]
):
    table = PaymentAmountReservationTable
