from dishka import Provider, Scope, provide

from src.modules.billing.payment_identifiers.app.allocation import (
    PaymentAmountAllocationQuery,
)
from src.modules.billing.payment_identifiers.app.reservations import (
    PaymentAmountReservationService,
)
from src.modules.billing.payment_identifiers.infra.mysql import (
    PaymentAmountReservationRepository,
)
from src.modules.billing.payment_identifiers.infra.readers import (
    PaymentAmountReader,
)
from src.modules.billing.payment_identifiers.interfaces import (
    IPaymentAmountAllocationQuery,
    IPaymentAmountReservationService,
)


class PaymentIdentifierProvider(Provider):
    scope = Scope.REQUEST
    reader = provide(PaymentAmountReader)
    repository = provide(PaymentAmountReservationRepository)
    allocation = provide(
        PaymentAmountAllocationQuery, provides=IPaymentAmountAllocationQuery
    )
    reservation = provide(
        PaymentAmountReservationService,
        provides=IPaymentAmountReservationService,
    )
