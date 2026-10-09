from datetime import UTC, datetime, timedelta

from papilio.errors.exceptions import NotFoundException

from src.config.settings import PapilioSettings
from src.modules.accounts.customers.app.policies import CustomerAccessPolicy
from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.network.routing.interfaces import IHostGroupService
from src.modules.operations.preferences.interfaces import IPreferencesService
from src.modules.sales.catalog.interfaces import IPlanService
from src.modules.sales.trials.app.policies import TrialEligibility
from src.modules.sales.trials.domain.dtos import TrialPolicy
from src.modules.sales.trials.domain.results import TrialAvailability
from src.modules.sales.trials.infra.readers import TrialUsageReader
from src.modules.sales.trials.interfaces import ITrialPolicyQuery


class TrialPolicyQuery:
    def __init__(
        self, preferences: IPreferencesService, settings: PapilioSettings
    ) -> None:
        self.preferences = preferences
        self.settings = settings

    async def current(self) -> TrialPolicy:
        result = (
            await self.preferences.current()
        ).values.trials or self.settings.trials.policy
        return result

    def capacity_valid(self, policy: TrialPolicy) -> bool:
        capacity = self.settings.trials
        return (
            policy.max_claims_per_customer <= capacity.max_claims_per_customer
            and policy.cooldown_seconds <= capacity.max_cooldown_seconds
            and policy.quota_bytes <= capacity.max_quota_bytes
            and policy.duration_days <= capacity.max_duration_days
        )


class TrialQuery:
    def __init__(
        self,
        policy: ITrialPolicyQuery,
        usage: TrialUsageReader,
        customers: ICustomerService,
        plans: IPlanService,
        groups: IHostGroupService,
    ) -> None:
        self.policy = policy
        self.usage = usage
        self.customers = customers
        self.plans = plans
        self.groups = groups

    async def availability(self, customer_id: int) -> TrialAvailability:
        policy = await self.policy.current()
        customer = await self.customers.get(customer_id)
        usage = await self.usage.read(
            customer_id, TrialEligibility.active_statuses, current=False
        )
        valid = self.policy.capacity_valid(policy)
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        reason = TrialEligibility.reason(policy, usage, valid, now)
        if reason is None and policy.plan_id is not None:
            try:
                plan = await self.plans.get(policy.plan_id)
                if not plan.is_active:
                    reason = "plan_inactive"
                elif plan.group_id is not None:
                    group = await self.groups.get(plan.group_id)
                    if not group.is_enabled:
                        reason = "plan_group_disabled"
            except NotFoundException:
                reason = "trial_source_missing"
        if not CustomerAccessPolicy.services_available(customer):
            reason = "customer_inactive"
        return TrialAvailability(
            policy=policy,
            capacity_valid=valid,
            eligible=reason is None,
            reason=reason,
            claims=usage.claims,
            next_claim_at=None
            if usage.latest_claim_at is None
            else usage.latest_claim_at
            + timedelta(seconds=policy.cooldown_seconds),
        )
