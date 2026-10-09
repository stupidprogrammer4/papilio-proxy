from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.accounts.customers.domain.dtos import (
    CustomerAccessSearch,
    CustomerAccessWrite,
    CustomerCreate,
    CustomerProfileWrite,
    CustomerSearch,
)
from src.modules.accounts.customers.domain.models import (
    CustomerAccessChangeModel,
    CustomerModel,
)
from src.modules.accounts.customers.domain.results import (
    ResellerCustomerAccessActor,
)
from src.modules.accounts.customers.interfaces import (
    ICustomerAccessCommand,
    ICustomerAccessQuery,
    ICustomerService,
)
from src.modules.accounts.resellers.app.policies import (
    ResellerCapacity,
    ResellerDelegation,
    conflict,
    missing,
)
from src.modules.accounts.resellers.domain.dtos import ResellerPolicy
from src.modules.accounts.resellers.domain.models import ResellerCustomerModel
from src.modules.accounts.resellers.domain.results import ResellerPrincipal
from src.modules.accounts.resellers.infra.mysql import (
    ResellerAccountRepository,
    ResellerCustomerRepository,
    ResellerRepository,
)
from src.modules.accounts.resellers.infra.readers import ResellerCustomerReader


class ResellerCustomerCommand:
    def __init__(
        self,
        resellers: ResellerRepository,
        accounts: ResellerAccountRepository,
        ownership: ResellerCustomerRepository,
        reader: ResellerCustomerReader,
        customers: ICustomerService,
        access: ICustomerAccessCommand,
        settings: PapilioSettings,
    ) -> None:
        self.resellers = resellers
        self.accounts = accounts
        self.ownership = ownership
        self.reader = reader
        self.customers = customers
        self.access = access
        self.settings = settings

    @handle_conflicts
    @transactional
    async def create(
        self,
        principal: ResellerPrincipal,
        data: CustomerCreate,
    ) -> CustomerModel:
        reseller = await self.resellers.locked(principal.reseller_id)
        if reseller is None:
            raise missing("reseller", principal.reseller_id)
        actor = await self.accounts.owned(
            reseller.id, principal.account_id, True
        )
        ResellerDelegation.principal(
            reseller, actor, principal, "customers:create", self.settings
        )
        capacity = ResellerCapacity.configured(self.settings)
        policy = ResellerPolicy.model_validate_json(reseller.policy_json)
        ResellerCapacity.validate(policy, capacity)
        if not policy.customer_creation_enabled:
            raise conflict("reseller_customer_creation_disabled")
        if (
            data.access is not None
            and data.access != policy.new_customer_access
            and not policy.customer_access_override_enabled
        ):
            raise conflict("reseller_customer_access_denied")
        if (
            await self.ownership.count_locked(reseller.id)
            >= policy.customer_capacity
        ):
            raise conflict("reseller_customer_capacity")
        customer = await self.customers.create(
            CustomerCreate(
                display_name=data.display_name,
                telegram_id=data.telegram_id,
                access=data.access or policy.new_customer_access,
            )
        )
        await self.ownership.create(
            ResellerCustomerModel(
                reseller_id=reseller.id, customer_id=customer.id
            )
        )
        return customer

    @transactional
    async def update_profile(
        self,
        principal: ResellerPrincipal,
        id: int,
        data: CustomerProfileWrite,
    ) -> CustomerModel:
        reseller = await self.resellers.locked(principal.reseller_id)
        if reseller is None:
            raise missing("reseller", principal.reseller_id)
        actor = await self.accounts.owned(
            reseller.id, principal.account_id, True
        )
        ResellerDelegation.principal(
            reseller, actor, principal, "customers:update", self.settings
        )
        owned = await self.reader.owned(reseller.id, id)
        if owned is None:
            raise missing("reseller_customer", id)
        result = await self.customers.update_profile(id, data)
        return result

    @transactional
    async def update_access(
        self, principal: ResellerPrincipal, id: int, data: CustomerAccessWrite
    ) -> CustomerModel:
        reseller = await self.resellers.locked(principal.reseller_id)
        if reseller is None:
            raise missing("reseller", principal.reseller_id)
        actor = await self.accounts.owned(
            reseller.id, principal.account_id, True
        )
        ResellerDelegation.principal(
            reseller, actor, principal, "customers:update", self.settings
        )
        owned = await self.reader.owned(reseller.id, id)
        if owned is None:
            raise missing("reseller_customer", id)
        policy = ResellerPolicy.model_validate_json(reseller.policy_json)
        if not policy.customer_access_override_enabled:
            raise conflict("reseller_customer_access_denied")
        result = await self.access.update(
            id,
            data,
            ResellerCustomerAccessActor(reseller.id, principal.account_id),
        )
        return result


class ResellerCustomerQuery:
    def __init__(
        self,
        reader: ResellerCustomerReader,
        access: ICustomerAccessQuery,
        settings: PapilioSettings,
    ) -> None:
        self.reader = reader
        self.access = access
        self.settings = settings

    async def get(self, reseller_id: int, customer_id: int) -> CustomerModel:
        result = await self.reader.owned(reseller_id, customer_id)
        if result is None:
            raise missing("reseller_customer", customer_id)
        return result.customer

    async def search(
        self,
        reseller_id: int,
        data: CustomerSearch,
    ) -> ServicePage[CustomerModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.reader.page(
            reseller_id, data.q, (data.page - 1) * limit, limit
        )
        return service_page(result, limit)

    async def access_history(
        self, reseller_id: int, customer_id: int, data: CustomerAccessSearch
    ) -> ServicePage[CustomerAccessChangeModel]:
        await self.get(reseller_id, customer_id)
        result = await self.access.search(customer_id, data)
        return result
