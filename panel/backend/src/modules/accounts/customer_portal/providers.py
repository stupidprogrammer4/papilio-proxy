from dishka import Provider, Scope, provide

from src.modules.accounts.customer_portal.app.commands import (
    CustomerAccountCommand,
)
from src.modules.accounts.customer_portal.interfaces import (
    ICustomerAccountCommand,
)


class CustomerAccountProvider(Provider):
    scope = Scope.REQUEST
    command = provide(CustomerAccountCommand, provides=ICustomerAccountCommand)
