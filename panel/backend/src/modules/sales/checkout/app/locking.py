from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.sales.checkout.app.errors import checkout_missing
from src.modules.sales.checkout.domain.models import CheckoutIntentModel
from src.modules.sales.checkout.infra.mysql import CheckoutIntentRepository
from src.modules.sales.checkout.interfaces import ICheckoutAttemptService


class CheckoutIntentLockCommand:
    """Admit one existing intent within its caller's native transaction.

    The caller owns the outer transactional scope. Immutable owner/key facts
    choose the lock order; all decisions use the subsequent current intent.
    """

    def __init__(
        self,
        customers: ICustomerService,
        attempts: ICheckoutAttemptService,
        intents: CheckoutIntentRepository,
    ) -> None:
        self.customers, self.attempts, self.intents = (
            customers,
            attempts,
            intents,
        )

    async def owned(self, customer_id: int, id: int) -> CheckoutIntentModel:
        await self.customers.locked(customer_id)
        identity = await self.intents.identity(id)
        if identity is None or identity.customer_id != customer_id:
            raise checkout_missing(id)
        await self.attempts.reserve(customer_id, identity.request_key, None)
        row = await self.intents.owned_current(id, customer_id)
        if row is None or row.request_key != identity.request_key:
            raise checkout_missing(id)
        return row

    async def known(self, id: int) -> CheckoutIntentModel:
        identity = await self.intents.identity(id)
        if identity is None:
            raise checkout_missing(id)
        result = await self.owned(identity.customer_id, id)
        return result
