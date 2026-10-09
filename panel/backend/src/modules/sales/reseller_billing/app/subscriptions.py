from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.accounts.resellers.app.policies import missing
from src.modules.accounts.resellers.interfaces import (
    IResellerCustomerQuery,
    IResellerRegistryQuery,
)
from src.modules.sales.reseller_billing.infra.subscriptions import (
    ResellerSubscriptionReader,
)
from src.modules.sales.subscriptions.domain.dtos import SubscriptionSearch
from src.modules.sales.subscriptions.domain.models import SubscriptionModel


class ResellerSubscriptionQuery:
    def __init__(
        self,
        reader: ResellerSubscriptionReader,
        resellers: IResellerRegistryQuery,
        customers: IResellerCustomerQuery,
        settings: PapilioSettings,
    ) -> None:
        self.reader = reader
        self.resellers = resellers
        self.customers = customers
        self.settings = settings

    async def get(self, reseller_id: int, id: int) -> SubscriptionModel:
        result = await self.reader.owned(reseller_id, id)
        if result is None:
            raise missing("reseller_subscription", id)
        return result

    async def search(
        self, reseller_id: int, data: SubscriptionSearch
    ) -> ServicePage[SubscriptionModel]:
        await self.resellers.get(reseller_id)
        if data.customer_id is not None:
            await self.customers.get(reseller_id, data.customer_id)
        limit = page_size(self.settings, data.per_page)
        result = await self.reader.page(
            reseller_id,
            data.customer_id,
            data.status,
            (data.page - 1) * limit,
            limit,
        )
        return service_page(result, limit)
