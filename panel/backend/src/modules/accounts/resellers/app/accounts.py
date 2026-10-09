from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.accounts.resellers.app.policies import (
    ResellerCapacity,
    ResellerDelegation,
    conflict,
    missing,
)
from src.modules.accounts.resellers.domain.dtos import (
    ResellerAccountCreate,
    ResellerAccountWrite,
    ResellerPasswordWrite,
    ResellerPolicy,
    ResellerScopes,
    ResellerSearch,
)
from src.modules.accounts.resellers.domain.models import (
    ResellerAccountChangeModel,
    ResellerAccountModel,
    ResellerModel,
)
from src.modules.accounts.resellers.domain.results import ResellerAccountActor
from src.modules.accounts.resellers.infra.mysql import (
    ResellerAccountChangeRepository,
    ResellerAccountRepository,
    ResellerRepository,
)
from src.modules.accounts.resellers.interfaces import (
    IResellerAccountQuery,
    IResellerRegistryQuery,
)
from src.modules.accounts.staff.app.passwords import Passwords
from src.modules.accounts.staff.infra.readers import StaffAuthorityReader


class ResellerAccountCommand:
    def __init__(
        self,
        accounts: ResellerAccountRepository,
        resellers: ResellerRepository,
        changes: ResellerAccountChangeRepository,
        passwords: Passwords,
        staff_authority: StaffAuthorityReader,
        settings: PapilioSettings,
    ) -> None:
        self.accounts = accounts
        self.resellers = resellers
        self.changes = changes
        self.passwords = passwords
        self.staff_authority = staff_authority
        self.settings = settings

    async def _authority(
        self,
        reseller_id: int,
        actor: ResellerAccountActor,
        level: str,
    ) -> tuple[ResellerModel, frozenset[str]]:
        if actor.staff_id is not None:
            staff = await self.staff_authority.access(actor.staff_id, True)
            ResellerDelegation.staff(staff, "manage")
        reseller = await self.resellers.locked(reseller_id)
        if reseller is None:
            raise missing("reseller", reseller_id)
        if actor.principal is None:
            return reseller, frozenset({"*"})
        principal = actor.principal
        account = await self.accounts.owned(
            reseller_id, principal.account_id, True
        )
        scopes = ResellerDelegation.principal(
            reseller, account, principal, f"team:{level}", self.settings
        )
        return reseller, scopes

    @handle_conflicts
    @transactional
    async def create(
        self,
        reseller_id: int,
        data: ResellerAccountCreate,
        actor: ResellerAccountActor,
    ) -> ResellerAccountModel:
        reseller, authority = await self._authority(
            reseller_id, actor, "create"
        )
        capacity = ResellerCapacity.configured(self.settings)
        policy = ResellerPolicy.model_validate_json(reseller.policy_json)
        ResellerCapacity.validate(policy, capacity)
        ResellerCapacity.scopes(data, capacity)
        ResellerDelegation.verify(authority, data.scopes)
        if (
            await self.accounts.count_locked(reseller_id)
            >= policy.account_capacity
        ):
            raise conflict("reseller_account_capacity")
        hashed = await self.passwords.hash(data.password.get_secret_value())
        result = await self.accounts.create(
            ResellerAccountModel(
                reseller_id=reseller_id,
                username=data.username,
                password_hash=hashed,
                is_active=data.is_active,
                scopes_json=ResellerScopes(
                    scopes=data.scopes
                ).model_dump_json(),
            )
        )
        await self._record(result, actor, "create", "ثبت حساب نمایندگی")
        return result

    @transactional
    async def update(
        self,
        reseller_id: int,
        id: int,
        data: ResellerAccountWrite,
        actor: ResellerAccountActor,
    ) -> ResellerAccountModel:
        reseller, authority = await self._authority(
            reseller_id, actor, "update"
        )
        capacity = ResellerCapacity.configured(self.settings)
        ResellerCapacity.scopes(data, capacity)
        target = await self.accounts.owned(reseller_id, id, True)
        if target is None:
            raise missing("reseller_account", id)
        if target.revision != data.expected_revision:
            raise conflict("reseller_account_revision_changed")
        old_scopes = ResellerScopes.model_validate_json(target.scopes_json)
        ResellerDelegation.verify(authority, old_scopes.scopes)
        ResellerDelegation.verify(authority, data.scopes)
        policy = ResellerPolicy.model_validate_json(reseller.policy_json)
        if (
            policy.require_active_owner
            and target.is_active
            and "*" in old_scopes.scopes
            and (not data.is_active or "*" not in data.scopes)
        ):
            accounts = await self.accounts.active(
                reseller_id, capacity.max_accounts_per_reseller + 1
            )
            if len(accounts) > capacity.max_accounts_per_reseller:
                raise conflict("reseller_account_capacity")
            if not any(
                row.id != id
                and "*"
                in ResellerScopes.model_validate_json(row.scopes_json).scopes
                for row in accounts
            ):
                raise conflict("reseller_last_owner")
        await self.accounts.update_row_by_id(
            id,
            ResellerAccountModel.patch(
                is_active=data.is_active,
                revision=target.revision + 1,
                scopes_json=ResellerScopes(
                    scopes=data.scopes
                ).model_dump_json(),
            ),
        )
        result = await self.accounts.owned(reseller_id, id, True)
        assert result is not None
        await self._record(result, actor, "access", data.reason)
        return result

    @transactional
    async def reset_password(
        self,
        reseller_id: int,
        id: int,
        data: ResellerPasswordWrite,
        actor: ResellerAccountActor,
    ) -> ResellerAccountModel:
        _, authority = await self._authority(reseller_id, actor, "manage")
        target = await self.accounts.owned(reseller_id, id, True)
        if target is None:
            raise missing("reseller_account", id)
        if target.revision != data.expected_revision:
            raise conflict("reseller_account_revision_changed")
        grants = ResellerScopes.model_validate_json(target.scopes_json)
        ResellerDelegation.verify(authority, grants.scopes)
        hashed = await self.passwords.hash(data.password.get_secret_value())
        await self.accounts.update_row_by_id(
            id,
            ResellerAccountModel.patch(
                password_hash=hashed,
                revision=target.revision + 1,
            ),
        )
        result = await self.accounts.owned(reseller_id, id, True)
        assert result is not None
        await self._record(result, actor, "password", data.reason)
        return result

    async def _record(
        self,
        account: ResellerAccountModel,
        actor: ResellerAccountActor,
        action: str,
        reason: str,
    ) -> None:
        await self.changes.create(
            ResellerAccountChangeModel(
                reseller_id=account.reseller_id,
                account_id=account.id,
                staff_id=actor.staff_id,
                actor_account_id=actor.principal.account_id
                if actor.principal is not None
                else None,
                action=action,
                revision=account.revision,
                is_active=account.is_active,
                scopes_json=account.scopes_json,
                reason=reason,
            )
        )


class ResellerAccountQuery:
    def __init__(
        self,
        repo: ResellerAccountRepository,
        resellers: IResellerRegistryQuery,
        settings: PapilioSettings,
    ) -> None:
        self.repo = repo
        self.settings = settings
        self.resellers = resellers

    async def get(self, reseller_id: int, id: int) -> ResellerAccountModel:
        result = await self.repo.owned(reseller_id, id)
        if result is None:
            raise missing("reseller_account", id)
        return result

    async def search(
        self,
        reseller_id: int,
        data: ResellerSearch,
    ) -> ServicePage[ResellerAccountModel]:
        await self.resellers.get(reseller_id)
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page(
            reseller_id, data.q, (data.page - 1) * limit, limit
        )
        return service_page(result, limit)


class ResellerAccountHistoryQuery:
    def __init__(
        self,
        repo: ResellerAccountChangeRepository,
        accounts: IResellerAccountQuery,
        settings: PapilioSettings,
    ) -> None:
        self.repo = repo
        self.settings = settings
        self.accounts = accounts

    async def search(
        self,
        reseller_id: int,
        account_id: int,
        data: ResellerSearch,
    ) -> ServicePage[ResellerAccountChangeModel]:
        await self.accounts.get(reseller_id, account_id)
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page(
            reseller_id, account_id, (data.page - 1) * limit, limit
        )
        return service_page(result, limit)
