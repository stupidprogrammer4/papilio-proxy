from papilio.infra.db.transaction import active_transaction
from redis.exceptions import RedisError
from taskiq.exceptions import SendTaskError

from src.config.settings import PapilioSettings
from src.modules.sales.checkout.infra.mysql import CheckoutIntentRepository
from src.modules.sales.checkout.interfaces import ICheckoutTaskPublisher
from src.modules.sales.checkout.tasks.schedulers.recovery import (
    RecoverCheckout,
)


class CheckoutTaskPublisher:
    async def enqueue(self, id: int) -> bool:
        if active_transaction() is not None:
            raise RuntimeError(
                "Checkout publication requires confirmed native commit"
            )
        try:
            await RecoverCheckout.enqueue(checkout_id=id)
        except (RedisError, SendTaskError):
            return False
        return True


class CheckoutFundingPublisher:
    def __init__(
        self,
        intents: CheckoutIntentRepository,
        publisher: ICheckoutTaskPublisher,
        settings: PapilioSettings,
    ) -> None:
        self.intents, self.publisher, self.settings = (
            intents,
            publisher,
            settings,
        )

    async def publish(self, topup_id: int) -> bool:
        if active_transaction() is not None:
            raise RuntimeError(
                "Funding publication requires confirmed native commit"
            )
        if self.settings.purchase_intents is None:
            return False
        row = await self.intents.by_topup(topup_id)
        if row is None:
            return False
        result = await self.publisher.enqueue(row.id)
        return result
