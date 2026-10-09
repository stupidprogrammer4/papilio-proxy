from dishka import Provider, Scope, provide

from src.modules.accounts.customers.app.access import (
    CustomerAccessCommand,
    CustomerAccessQuery,
)
from src.modules.accounts.customers.app.configurations import (
    CustomerConfigurationQuery,
)
from src.modules.accounts.customers.app.services import CustomerService
from src.modules.accounts.customers.infra.configurations import (
    CustomerConfigurationReader,
)
from src.modules.accounts.customers.infra.mysql import (
    CustomerAccessChangeRepository,
    CustomerRepository,
)
from src.modules.accounts.customers.interfaces import (
    ICustomerAccessCommand,
    ICustomerAccessQuery,
    ICustomerConfigurationQuery,
    ICustomerService,
)


class CustomerProvider(Provider):
    configurations_reader = provide(CustomerConfigurationReader)
    configurations_query = provide(
        CustomerConfigurationQuery, provides=ICustomerConfigurationQuery
    )
    scope = Scope.REQUEST
    repository = provide(CustomerRepository)
    service = provide(CustomerService, provides=ICustomerService)
    changes = provide(CustomerAccessChangeRepository)
    access = provide(CustomerAccessCommand, provides=ICustomerAccessCommand)
    access_query = provide(CustomerAccessQuery, provides=ICustomerAccessQuery)
