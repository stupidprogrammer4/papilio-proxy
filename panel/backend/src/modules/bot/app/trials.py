from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.bot.domain.dtos import BotIdentity, BotTrialClaim
from src.modules.sales.subscriptions.domain.models import SubscriptionModel
from src.modules.sales.trials.domain.dtos import TrialClaim
from src.modules.sales.trials.domain.results import TrialAvailability
from src.modules.sales.trials.interfaces import ITrialCommand, ITrialQuery


class BotTrialCommand:
    def __init__(
        self,
        customers: ICustomerService,
        trials: ITrialCommand,
        query: ITrialQuery,
    ) -> None:
        self.customers = customers
        self.trials = trials
        self.query = query

    async def availability(self, data: BotIdentity) -> TrialAvailability:
        customer = await self.customers.ensure_telegram(
            data.telegram_id, data.display_name
        )
        result = await self.query.availability(customer.id)
        return result

    async def claim(self, data: BotTrialClaim) -> SubscriptionModel:
        customer = await self.customers.ensure_telegram(
            data.telegram_id, data.display_name
        )
        result = await self.trials.claim(
            customer.id, TrialClaim(request_key=data.request_key)
        )
        return result
