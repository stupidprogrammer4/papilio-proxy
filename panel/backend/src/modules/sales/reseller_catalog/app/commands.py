from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional

from src.config.settings import PapilioSettings
from src.modules.accounts.resellers.app.policies import (
    ResellerCapacity,
    ResellerDelegation,
    conflict,
    missing,
)
from src.modules.accounts.resellers.domain.dtos import ResellerPolicy
from src.modules.accounts.resellers.interfaces import IResellerRegistryQuery
from src.modules.accounts.staff.infra.readers import StaffAuthorityReader
from src.modules.sales.catalog.interfaces import IPlanService
from src.modules.sales.reseller_catalog.domain.dtos import (
    AgreementCreate,
    AgreementWrite,
)
from src.modules.sales.reseller_catalog.domain.models import (
    ResellerPlanChangeModel,
    ResellerPlanModel,
)
from src.modules.sales.reseller_catalog.infra.mysql import (
    ResellerPlanChangeRepository,
    ResellerPlanRepository,
)


class ResellerPlanCommand:
    def __init__(
        self,
        agreements: ResellerPlanRepository,
        changes: ResellerPlanChangeRepository,
        resellers: IResellerRegistryQuery,
        plans: IPlanService,
        authority: StaffAuthorityReader,
        settings: PapilioSettings,
    ) -> None:
        self.agreements = agreements
        self.changes = changes
        self.resellers = resellers
        self.plans = plans
        self.authority = authority
        self.settings = settings

    @handle_conflicts
    @transactional
    async def create(
        self, reseller_id: int, data: AgreementCreate, staff_id: int
    ) -> ResellerPlanModel:
        staff = await self.authority.access(staff_id, True)
        ResellerDelegation.staff(staff, "manage")
        reseller = await self.resellers.locked(reseller_id)
        capacity = ResellerCapacity.configured(self.settings)
        policy = ResellerPolicy.model_validate_json(reseller.policy_json)
        ResellerCapacity.validate(policy, capacity)
        await self.plans.get(data.plan_id)
        count = await self.agreements.count_locked(reseller_id)
        if count >= policy.plan_capacity:
            raise conflict("reseller_plan_capacity")
        result = await self.agreements.create(
            ResellerPlanModel(
                reseller_id=reseller_id,
                plan_id=data.plan_id,
                enabled=data.enabled,
                price_json=data.price.model_dump_json(),
            )
        )
        await self._record(result, staff_id, data.reason)
        return result

    @transactional
    async def update(
        self, reseller_id: int, id: int, data: AgreementWrite, staff_id: int
    ) -> ResellerPlanModel:
        staff = await self.authority.access(staff_id, True)
        ResellerDelegation.staff(staff, "manage")
        reseller = await self.resellers.locked(reseller_id)
        if data.enabled:
            ResellerCapacity.validate(
                ResellerPolicy.model_validate_json(reseller.policy_json),
                ResellerCapacity.configured(self.settings),
            )
        current = await self.agreements.owned(reseller_id, id, True)
        if current is None:
            raise missing("reseller_plan", id)
        if current.revision != data.expected_revision:
            raise conflict("reseller_plan_revision_changed")
        await self.agreements.update_row_by_id(
            id,
            ResellerPlanModel.patch(
                enabled=data.enabled,
                revision=current.revision + 1,
                price_json=data.price.model_dump_json(),
            ),
        )
        result = await self.agreements.owned(reseller_id, id, True)
        assert result is not None
        await self._record(result, staff_id, data.reason)
        return result

    async def _record(
        self, agreement: ResellerPlanModel, staff_id: int, reason: str
    ) -> None:
        await self.changes.create(
            ResellerPlanChangeModel(
                agreement_id=agreement.id,
                staff_id=staff_id,
                revision=agreement.revision,
                enabled=agreement.enabled,
                price_json=agreement.price_json,
                reason=reason,
            )
        )
