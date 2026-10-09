from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.accounts.customers.domain.dtos import CustomerCreate
from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.accounts.resellers.app.policies import (
    ResellerCapacity,
    ResellerDelegation,
    conflict,
    missing,
)
from src.modules.accounts.resellers.domain.dtos import (
    ResellerCreate,
    ResellerDefaults,
    ResellerScopes,
    ResellerSearch,
    ResellerWrite,
)
from src.modules.accounts.resellers.domain.models import (
    ResellerAccountChangeModel,
    ResellerAccountModel,
    ResellerChangeModel,
    ResellerModel,
)
from src.modules.accounts.resellers.domain.results import CreatedReseller
from src.modules.accounts.resellers.infra.mysql import (
    ResellerAccountChangeRepository,
    ResellerAccountRepository,
    ResellerChangeRepository,
    ResellerRepository,
)
from src.modules.accounts.resellers.interfaces import IResellerRegistryQuery
from src.modules.accounts.staff.app.passwords import Passwords
from src.modules.accounts.staff.infra.readers import StaffAuthorityReader
from src.modules.operations.preferences.interfaces import IPreferencesService


class ResellerRegistryCommand:
    def __init__(
        self,
        resellers: ResellerRepository,
        accounts: ResellerAccountRepository,
        changes: ResellerChangeRepository,
        account_changes: ResellerAccountChangeRepository,
        customers: ICustomerService,
        preferences: IPreferencesService,
        passwords: Passwords,
        settings: PapilioSettings,
        staff_authority: StaffAuthorityReader,
    ) -> None:
        self.resellers = resellers
        self.accounts = accounts
        self.changes = changes
        self.account_changes = account_changes
        self.customers = customers
        self.preferences = preferences
        self.passwords = passwords
        self.settings = settings
        self.staff_authority = staff_authority

    @handle_conflicts
    @transactional
    async def create(
        self, data: ResellerCreate, staff_id: int
    ) -> CreatedReseller:
        authority = await self.staff_authority.access(staff_id, True)
        ResellerDelegation.staff(authority, "create")
        capacity = ResellerCapacity.configured(self.settings)
        defaults = (await self.preferences.current()).values.reseller_defaults
        if defaults is None:
            defaults = capacity.defaults
        policy = data.policy or defaults.policy
        access = data.access or defaults.access
        owner_access = data.owner_access or defaults.owner_access
        owner_active = data.owner_is_active
        if owner_active is None:
            owner_active = defaults.owner_is_active
        ResellerCapacity.validate(policy, capacity)
        ResellerCapacity.scopes(owner_access, capacity)
        if policy.require_active_owner and (
            not owner_active or "*" not in owner_access.scopes
        ):
            raise conflict("reseller_owner_required")
        password_hash = await self.passwords.hash(
            data.owner.password.get_secret_value()
        )
        customer = await self.customers.create(
            CustomerCreate(
                display_name=data.title,
                access=defaults.wallet_customer_access,
            )
        )
        reseller = await self.resellers.create(
            ResellerModel(
                code=data.code,
                title=data.title,
                wallet_customer_id=customer.id,
                policy_json=policy.model_dump_json(),
                created_by_staff_id=staff_id,
                **access.model_dump(),
            )
        )
        owner = await self.accounts.create(
            ResellerAccountModel(
                reseller_id=reseller.id,
                username=data.owner.username,
                password_hash=password_hash,
                scopes_json=owner_access.model_dump_json(),
                is_active=owner_active,
            )
        )
        await self.changes.create(
            ResellerChangeModel(
                reseller_id=reseller.id,
                staff_id=staff_id,
                revision=1,
                title=reseller.title,
                policy_json=reseller.policy_json,
                reason="ثبت نمایندگی",
                **access.model_dump(),
            )
        )
        await self.account_changes.create(
            ResellerAccountChangeModel(
                reseller_id=reseller.id,
                account_id=owner.id,
                staff_id=staff_id,
                action="create",
                revision=1,
                is_active=owner_active,
                scopes_json=owner.scopes_json,
                reason="ثبت مدیر نمایندگی",
            )
        )
        return CreatedReseller(reseller, owner)

    @transactional
    async def update(
        self, id: int, data: ResellerWrite, staff_id: int
    ) -> ResellerModel:
        authority = await self.staff_authority.access(staff_id, True)
        ResellerDelegation.staff(authority, "update")
        capacity = ResellerCapacity.configured(self.settings)
        row = await self.resellers.locked(id)
        if row is None:
            raise missing("reseller", id)
        if row.revision != data.expected_revision:
            raise conflict("reseller_revision_changed")
        if any(data.access.model_dump().values()):
            ResellerCapacity.validate(data.policy, capacity)
        if data.policy.require_active_owner:
            accounts = await self.accounts.active(
                row.id, capacity.max_accounts_per_reseller + 1
            )
            if len(accounts) > capacity.max_accounts_per_reseller:
                raise conflict("reseller_account_capacity")
            if not any(
                "*"
                in ResellerScopes.model_validate_json(
                    account.scopes_json
                ).scopes
                for account in accounts
            ):
                raise conflict("reseller_owner_required")
        changed_access = (
            row.login_enabled != data.access.login_enabled
            or row.sales_enabled != data.access.sales_enabled
            or row.renewals_enabled != data.access.renewals_enabled
        )
        await self.resellers.update_row_by_id(
            id,
            ResellerModel.patch(
                title=data.title,
                revision=row.revision + 1,
                access_revision=row.access_revision + int(changed_access),
                login_enabled=data.access.login_enabled,
                sales_enabled=data.access.sales_enabled,
                renewals_enabled=data.access.renewals_enabled,
                policy_json=data.policy.model_dump_json(),
            ),
        )
        result = await self.resellers.locked(id)
        assert result is not None
        await self.changes.create(
            ResellerChangeModel(
                reseller_id=id,
                staff_id=staff_id,
                revision=result.revision,
                title=result.title,
                policy_json=result.policy_json,
                reason=data.reason,
                **data.access.model_dump(),
            )
        )
        return result


class ResellerRegistryQuery:
    def __init__(
        self,
        repo: ResellerRepository,
        preferences: IPreferencesService,
        settings: PapilioSettings,
    ) -> None:
        self.repo = repo
        self.preferences = preferences
        self.settings = settings

    async def defaults(self) -> ResellerDefaults:
        snapshot = await self.preferences.current()
        result = snapshot.values.reseller_defaults
        if result is None:
            result = ResellerCapacity.configured(self.settings).defaults
        return result

    async def get(self, id: int) -> ResellerModel:
        result = await self.repo.get_by_id(id)
        if result is None:
            raise missing("reseller", id)
        return result

    async def locked(self, id: int) -> ResellerModel:
        result = await self.repo.locked(id)
        if result is None:
            raise missing("reseller", id)
        return result

    async def search(self, data: ResellerSearch) -> ServicePage[ResellerModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page(data.q, (data.page - 1) * limit, limit)
        return service_page(result, limit)


class ResellerRegistryHistoryQuery:
    def __init__(
        self,
        repo: ResellerChangeRepository,
        resellers: IResellerRegistryQuery,
        settings: PapilioSettings,
    ) -> None:
        self.repo = repo
        self.settings = settings
        self.resellers = resellers

    async def search(
        self, reseller_id: int, data: ResellerSearch
    ) -> ServicePage[ResellerChangeModel]:
        await self.resellers.get(reseller_id)
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page(
            reseller_id, (data.page - 1) * limit, limit
        )
        return service_page(result, limit)
