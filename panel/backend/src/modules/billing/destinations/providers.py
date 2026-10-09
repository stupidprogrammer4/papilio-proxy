from dishka import Provider, Scope, provide

from src.modules.billing.destinations.app.services import (
    PaymentDestinationService,
)
from src.modules.billing.destinations.infra.mysql import (
    PaymentDestinationRepository,
)
from src.modules.billing.destinations.interfaces import (
    IPaymentDestinationService,
)


class PaymentDestinationProvider(Provider):
    scope = Scope.REQUEST
    repo = provide(PaymentDestinationRepository)
    service = provide(
        PaymentDestinationService, provides=IPaymentDestinationService
    )
