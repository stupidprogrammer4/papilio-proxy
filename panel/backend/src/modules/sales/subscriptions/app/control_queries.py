from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.sales.subscriptions.domain.dtos import (
    SubscriptionControlSearch,
)
from src.modules.sales.subscriptions.domain.models import (
    SubscriptionControlModel,
)
from src.modules.sales.subscriptions.infra.mysql import (
    SubscriptionControlRepository,
)
from src.modules.sales.subscriptions.interfaces import ISubscriptionCommand


class SubscriptionControlQuery:
    def __init__(
        self,
        repo: SubscriptionControlRepository,
        subscriptions: ISubscriptionCommand,
        settings: PapilioSettings,
    ) -> None:
        self.repo = repo
        self.subscriptions = subscriptions
        self.settings = settings

    async def search(
        self, subscription_id: int, data: SubscriptionControlSearch
    ) -> ServicePage[SubscriptionControlModel]:
        await self.subscriptions.get(subscription_id)
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page(
            subscription_id, (data.page - 1) * limit, limit
        )
        return service_page(result, limit)
