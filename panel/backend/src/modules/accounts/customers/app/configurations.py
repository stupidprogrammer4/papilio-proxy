from src.config.pagination import ServicePage, page_size
from src.config.settings import PapilioSettings
from src.modules.accounts.customers.domain.configurations import (
    CustomerConfigurationRead,
    CustomerConfigurationSearch,
)
from src.modules.accounts.customers.infra.configurations import (
    CustomerConfigurationReader,
)
from src.modules.accounts.customers.interfaces import ICustomerService


class CustomerConfigurationQuery:
    def __init__(
        self,
        reader: CustomerConfigurationReader,
        customers: ICustomerService,
        settings: PapilioSettings,
    ) -> None:
        self.reader = reader
        self.customers = customers
        self.settings = settings

    async def search(
        self, customer_id: int, data: CustomerConfigurationSearch
    ) -> ServicePage[CustomerConfigurationRead]:
        await self.customers.get(customer_id)
        limit = page_size(self.settings, data.per_page)
        result = await self.reader.page(
            customer_id, data.subscription_id, (data.page - 1) * limit, limit
        )
        items = [
            CustomerConfigurationRead(
                profile_id=row.profile.id,
                subscription_id=row.subscription.id,
                customer_id=row.subscription.customer_id,
                plan_id=row.plan.id,
                plan_title=row.plan.title,
                configuration_id=row.configuration.id,
                configuration_label=row.configuration.label,
                node_id=row.node.id,
                node_label=row.node.label,
                protocol=row.configuration.protocol,
                status=row.subscription.status,
                desired_revision=row.configuration.revision,
                applied_revision=row.profile.applied_revision,
                quota_bytes=row.subscription.quota_bytes,
                used_bytes=row.subscription.used_bytes,
                expires_at=row.subscription.expires_at,
                auto_renew=row.subscription.auto_renew,
            )
            for row in result.items
        ]
        return ServicePage(
            items=items, total_items=result.total_items, per_page=limit
        )
