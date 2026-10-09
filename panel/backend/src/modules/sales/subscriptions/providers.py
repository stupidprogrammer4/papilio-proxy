from dishka import Provider, Scope, provide

from src.modules.sales.subscriptions.app.commands import SubscriptionCommand
from src.modules.sales.subscriptions.app.control import (
    SubscriptionControlCommand,
)
from src.modules.sales.subscriptions.app.control_queries import (
    SubscriptionControlQuery,
)
from src.modules.sales.subscriptions.app.customer_holds import (
    CustomerHoldCommand,
    CustomerHoldFinalizeCommand,
    CustomerHoldFinalizeQuery,
    CustomerHoldQuery,
)
from src.modules.sales.subscriptions.app.lifecycle import (
    SubscriptionLifecycleCommand,
    SubscriptionLifecycleQuery,
)
from src.modules.sales.subscriptions.app.queries import RenewalQuery
from src.modules.sales.subscriptions.app.renewal_quotes import (
    SubscriptionRenewalQuoteQuery,
)
from src.modules.sales.subscriptions.infra.mysql import (
    SubscriptionControlRepository,
    SubscriptionRepository,
)
from src.modules.sales.subscriptions.infra.readers import CustomerHoldReader
from src.modules.sales.subscriptions.interfaces import (
    ICustomerHoldCommand,
    ICustomerHoldFinalizeCommand,
    ICustomerHoldFinalizeQuery,
    ICustomerHoldQuery,
    IRenewalQuery,
    ISubscriptionCommand,
    ISubscriptionControlCommand,
    ISubscriptionControlQuery,
    ISubscriptionLifecycleCommand,
    ISubscriptionLifecycleQuery,
    ISubscriptionRenewalQuoteQuery,
)
from src.modules.sales.subscriptions.tasks.schedulers.customer_holds import (
    CheckCustomerHold,
    FinalizeCustomerHold,
    ScanCustomerHolds,
)
from src.modules.sales.subscriptions.tasks.schedulers.lifecycle import (
    CheckSubscriptionLifecycle,
    ScanSubscriptionLifecycle,
)
from src.modules.sales.subscriptions.tasks.schedulers.renewals import (
    RenewSubscription,
    ScanRenewals,
)


class SubscriptionProvider(Provider):
    scope = Scope.REQUEST
    repository = provide(SubscriptionRepository)
    renewal_quotes = provide(
        SubscriptionRenewalQuoteQuery, provides=ISubscriptionRenewalQuoteQuery
    )
    command = provide(SubscriptionCommand, provides=ISubscriptionCommand)
    renew_task = provide(RenewSubscription)
    scan_task = provide(ScanRenewals)
    renewal_query = provide(RenewalQuery, provides=IRenewalQuery)
    lifecycle_command = provide(
        SubscriptionLifecycleCommand, provides=ISubscriptionLifecycleCommand
    )
    lifecycle_query = provide(
        SubscriptionLifecycleQuery, provides=ISubscriptionLifecycleQuery
    )
    lifecycle_check_task = provide(CheckSubscriptionLifecycle)
    lifecycle_scan_task = provide(ScanSubscriptionLifecycle)
    control = provide(
        SubscriptionControlCommand, provides=ISubscriptionControlCommand
    )
    controls = provide(SubscriptionControlRepository)
    control_query = provide(
        SubscriptionControlQuery, provides=ISubscriptionControlQuery
    )
    hold_reader = provide(CustomerHoldReader)
    hold_command = provide(CustomerHoldCommand, provides=ICustomerHoldCommand)
    hold_query = provide(CustomerHoldQuery, provides=ICustomerHoldQuery)
    hold_check = provide(CheckCustomerHold)
    hold_scan = provide(ScanCustomerHolds)
    hold_finalize = provide(
        CustomerHoldFinalizeCommand, provides=ICustomerHoldFinalizeCommand
    )
    hold_finalize_query = provide(
        CustomerHoldFinalizeQuery, provides=ICustomerHoldFinalizeQuery
    )
    hold_finalize_task = provide(FinalizeCustomerHold)
