from dishka import Provider, Scope, provide

from src.modules.sales.attention.app.alerts import SubscriptionAlertCommand
from src.modules.sales.attention.app.commands import (
    SubscriptionAttentionCommand,
)
from src.modules.sales.attention.app.queries import SubscriptionAttentionQuery
from src.modules.sales.attention.app.renewal import (
    CustomerRenewalEligibilityQuery,
)
from src.modules.sales.attention.infra.mysql import (
    SubscriptionAttentionRepository,
)
from src.modules.sales.attention.infra.readers import (
    CustomerRenewalReader,
    SubscriptionAttentionReader,
)
from src.modules.sales.attention.interfaces import (
    ICustomerRenewalEligibilityQuery,
    ISubscriptionAlertCommand,
    ISubscriptionAttentionCommand,
    ISubscriptionAttentionQuery,
)
from src.modules.sales.attention.tasks.schedulers.checks import (
    CheckSubscriptionAttention,
    ScanSubscriptionAttention,
)


class SubscriptionAttentionProvider(Provider):
    renewal_eligibility = provide(
        CustomerRenewalEligibilityQuery,
        provides=ICustomerRenewalEligibilityQuery,
    )
    alerts = provide(
        SubscriptionAlertCommand, provides=ISubscriptionAlertCommand
    )
    scope = Scope.REQUEST
    repository = provide(SubscriptionAttentionRepository)
    reader = provide(SubscriptionAttentionReader)
    renewal_reader = provide(CustomerRenewalReader)
    command = provide(
        SubscriptionAttentionCommand, provides=ISubscriptionAttentionCommand
    )
    query = provide(
        SubscriptionAttentionQuery, provides=ISubscriptionAttentionQuery
    )
    check_task = provide(CheckSubscriptionAttention)
    scan_task = provide(ScanSubscriptionAttention)
