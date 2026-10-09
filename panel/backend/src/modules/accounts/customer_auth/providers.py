from dishka import Provider, Scope, provide

from src.modules.accounts.customer_auth.app.commands import CustomerAuthCommand
from src.modules.accounts.customer_auth.infra.mysql import (
    CustomerLoginRepository,
    CustomerSessionRepository,
)
from src.modules.accounts.customer_auth.infra.readers import (
    CustomerSessionReader,
)
from src.modules.accounts.customer_auth.interfaces import ICustomerAuthCommand


class CustomerAuthProvider(Provider):
    scope = Scope.REQUEST
    logins = provide(CustomerLoginRepository)
    sessions = provide(CustomerSessionRepository)
    reader = provide(CustomerSessionReader)
    auth = provide(CustomerAuthCommand, provides=ICustomerAuthCommand)
