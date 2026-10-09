from dishka import Provider, Scope, provide

from src.modules.sales.reseller_billing.app.catalog import CustomerCatalogQuery
from src.modules.sales.reseller_billing.app.queries import ResellerBillingQuery
from src.modules.sales.reseller_billing.app.subscriptions import (
    ResellerSubscriptionQuery,
)
from src.modules.sales.reseller_billing.infra.readers import (
    ResellerBillingReader,
)
from src.modules.sales.reseller_billing.infra.subscriptions import (
    ResellerSubscriptionReader,
)
from src.modules.sales.reseller_billing.interfaces import (
    ICustomerCatalogQuery,
    IResellerBillingQuery,
    IResellerSubscriptionQuery,
)


class ResellerBillingProvider(Provider):
    scope = Scope.REQUEST
    reader = provide(ResellerBillingReader)
    query = provide(ResellerBillingQuery, provides=IResellerBillingQuery)
    subscriptions_reader = provide(ResellerSubscriptionReader)
    subscriptions = provide(
        ResellerSubscriptionQuery, provides=IResellerSubscriptionQuery
    )

    customer_catalog = provide(
        CustomerCatalogQuery, provides=ICustomerCatalogQuery
    )
