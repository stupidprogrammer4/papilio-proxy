from datetime import UTC, datetime, timedelta

from papilio.errors.exceptions import ConflictException, NotFoundException
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional

from src.config.settings import PapilioSettings
from src.modules.accounts.customers.app.policies import CustomerAccessPolicy
from src.modules.accounts.customers.infra.mysql import CustomerRepository
from src.modules.network.ip_limits.domain.dtos import IpLimitChoice
from src.modules.network.ip_limits.domain.models import IpLimitPolicyModel
from src.modules.network.ip_limits.infra.mysql import IpLimitPolicyRepository
from src.modules.network.ip_limits.interfaces import (
    IIpLeaseTrackingService,
    IPurchasedIpPolicyService,
)
from src.modules.network.provisioning.interfaces import IProvisioningCommand
from src.modules.network.routing.interfaces import IHostGroupService
from src.modules.operations.preferences.interfaces import IPreferencesService
from src.modules.sales.catalog.domain.policies import (
    FulfillmentPolicy,
    QuotaPolicy,
)
from src.modules.sales.catalog.infra.mysql import PlanRepository
from src.modules.sales.subscriptions.domain.models import SubscriptionModel
from src.modules.sales.subscriptions.infra.mysql import SubscriptionRepository
from src.modules.sales.trials.app.policies import TrialEligibility
from src.modules.sales.trials.domain.dtos import TrialClaim
from src.modules.sales.trials.infra.readers import TrialUsageReader
from src.modules.sales.trials.interfaces import ITrialPolicyQuery


class TrialCommand:
    def __init__(
        self,
        customers: CustomerRepository,
        plans: PlanRepository,
        subscriptions: SubscriptionRepository,
        usage: TrialUsageReader,
        policy: ITrialPolicyQuery,
        groups: IHostGroupService,
        provisioning: IProvisioningCommand,
        preferences: IPreferencesService,
        ip_policies: IpLimitPolicyRepository,
        purchased_ip: IPurchasedIpPolicyService,
        ip_lease_tracking: IIpLeaseTrackingService,
        settings: PapilioSettings,
    ) -> None:
        self.customers = customers
        self.plans = plans
        self.subscriptions = subscriptions
        self.usage = usage
        self.policy = policy
        self.groups = groups
        self.provisioning = provisioning
        self.preferences = preferences
        self.ip_policies = ip_policies
        self.purchased_ip = purchased_ip
        self.ip_lease_tracking = ip_lease_tracking
        self.settings = settings

    @handle_conflicts
    @transactional
    async def claim(
        self, customer_id: int, data: TrialClaim
    ) -> SubscriptionModel:
        customer = await self.customers.locked(customer_id)
        if customer is None:
            raise NotFoundException(
                message="مشتری پیدا نشد.",
                message_code="customer_not_found",
                entity="customer",
                identifier="id",
                identifier_value=customer_id,
            )
        key = f"trial:{customer_id}:{data.request_key}"
        existing = await self.subscriptions.locked_by_purchase_key(key)
        if existing is not None:
            if (
                existing.customer_id != customer_id
                or existing.entitlement_kind != "trial"
            ):
                raise _conflict("purchase_key_reused", customer_id)
            return existing
        if not CustomerAccessPolicy.services_available(customer):
            raise _conflict("customer_inactive", customer_id)
        policy = await self.policy.current()
        usage = await self.usage.read(
            customer_id, TrialEligibility.active_statuses, current=True
        )
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        reason = TrialEligibility.reason(
            policy, usage, self.policy.capacity_valid(policy), now
        )
        if reason is not None:
            raise _conflict(reason, customer_id)
        if policy.plan_id is None:
            raise _conflict("trial_disabled", customer_id)
        plan = await self.plans.get_by_id(policy.plan_id)
        if plan is None:
            raise NotFoundException(
                message="پلن پیدا نشد.",
                message_code="plan_not_found",
                entity="plan",
                identifier="id",
                identifier_value=policy.plan_id,
            )
        if not plan.is_active:
            raise _conflict("plan_inactive", customer_id)
        if plan.group_id is not None:
            group = await self.groups.get(plan.group_id)
            if not group.is_enabled:
                raise _conflict("plan_group_disabled", customer_id)
        preferences = (await self.preferences.current()).values
        fulfillment = (
            FulfillmentPolicy.model_validate_json(plan.fulfillment_json)
            if plan.fulfillment_json is not None
            else preferences.fulfillment or self.settings.fulfillment.policy
        )
        quota = (
            QuotaPolicy.model_validate_json(plan.quota_policy_json)
            if plan.quota_policy_json is not None
            else preferences.quota_policy or self.settings.usage.policy
        )
        subscription = await self.subscriptions.create(
            SubscriptionModel(
                entitlement_kind="trial",
                trial_policy_json=policy.model_dump_json(),
                purchase_key=key,
                customer_id=customer_id,
                payer_customer_id=customer_id,
                plan_id=plan.id,
                group_id=plan.group_id,
                quota_bytes=policy.quota_bytes,
                base_quota_bytes=policy.quota_bytes,
                price_rial=0,
                duration_days=policy.duration_days,
                expires_at=now + timedelta(days=policy.duration_days),
                status="pending_provision",
                auto_renew=False,
                renewal_count=0,
                provisioning_managed=True,
                fulfillment_json=fulfillment.model_dump_json(),
                quota_policy_json=quota.model_dump_json(),
            )
        )
        await self.ip_lease_tracking.initialize_purchase(subscription.id)
        ip = (
            IpLimitChoice.model_validate_json(plan.ip_limit_json)
            if plan.ip_limit_json is not None
            else IpLimitChoice.model_validate(
                preferences.ip_defaults.model_dump()
            )
        )
        await self.purchased_ip.capture(
            subscription.id,
            plan.id,
            ip,
            "plan_override"
            if plan.ip_limit_json is not None
            else "purchase_defaults",
        )
        if plan.ip_limit_json is not None or ip.enabled:
            await self.ip_policies.create(
                IpLimitPolicyModel(
                    subscription_id=subscription.id, **ip.model_dump()
                )
            )
        await self.provisioning.queue(
            subscription.id, subscription.renewal_count, fulfillment
        )
        return subscription


def _conflict(code: str, customer_id: int) -> ConflictException:
    return ConflictException(
        message="دریافت اشتراک آزمایشی با شرایط فعلی ممکن نیست.",
        message_code=code,
        unique_dict={"customer_id": customer_id},
    )
