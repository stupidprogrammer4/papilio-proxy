from dishka import Provider, Scope, provide

from src.modules.accounts.resellers.app.accounts import (
    ResellerAccountCommand,
    ResellerAccountHistoryQuery,
    ResellerAccountQuery,
)
from src.modules.accounts.resellers.app.auth import (
    ResellerAuthCommand,
    ResellerAuthQuery,
)
from src.modules.accounts.resellers.app.customers import (
    ResellerCustomerCommand,
    ResellerCustomerQuery,
)
from src.modules.accounts.resellers.app.registry import (
    ResellerRegistryCommand,
    ResellerRegistryHistoryQuery,
    ResellerRegistryQuery,
)
from src.modules.accounts.resellers.infra.mysql import (
    ResellerAccountChangeRepository,
    ResellerAccountRepository,
    ResellerChangeRepository,
    ResellerCustomerRepository,
    ResellerRepository,
    ResellerSessionRepository,
)
from src.modules.accounts.resellers.infra.readers import (
    ResellerCustomerReader,
    ResellerSessionReader,
)
from src.modules.accounts.resellers.interfaces import (
    IResellerAccountCommand,
    IResellerAccountHistoryQuery,
    IResellerAccountQuery,
    IResellerAuthCommand,
    IResellerAuthQuery,
    IResellerCustomerCommand,
    IResellerCustomerQuery,
    IResellerRegistryCommand,
    IResellerRegistryHistoryQuery,
    IResellerRegistryQuery,
)


class ResellerProvider(Provider):
    scope = Scope.REQUEST
    registry_repo = provide(ResellerRepository)
    account_repo = provide(ResellerAccountRepository)
    session_repo = provide(ResellerSessionRepository)
    customer_repo = provide(ResellerCustomerRepository)
    changes_repo = provide(ResellerChangeRepository)
    account_changes_repo = provide(ResellerAccountChangeRepository)
    session_reader = provide(ResellerSessionReader)
    customer_reader = provide(ResellerCustomerReader)
    registry_command = provide(
        ResellerRegistryCommand, provides=IResellerRegistryCommand
    )
    registry_query = provide(
        ResellerRegistryQuery, provides=IResellerRegistryQuery
    )
    registry_history = provide(
        ResellerRegistryHistoryQuery, provides=IResellerRegistryHistoryQuery
    )
    account_command = provide(
        ResellerAccountCommand, provides=IResellerAccountCommand
    )
    account_query = provide(
        ResellerAccountQuery, provides=IResellerAccountQuery
    )
    account_history = provide(
        ResellerAccountHistoryQuery, provides=IResellerAccountHistoryQuery
    )
    auth_command = provide(ResellerAuthCommand, provides=IResellerAuthCommand)
    auth_query = provide(ResellerAuthQuery, provides=IResellerAuthQuery)
    customer_command = provide(
        ResellerCustomerCommand, provides=IResellerCustomerCommand
    )
    customer_query = provide(
        ResellerCustomerQuery, provides=IResellerCustomerQuery
    )
