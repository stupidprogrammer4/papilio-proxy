from datetime import UTC, datetime

from papilio.infra.db.tools.decorators import transactional

from src.config.settings import PapilioSettings
from src.modules.network.provisioning.interfaces import IProvisioningCommand
from src.modules.operations.automation.domain.dtos import ScheduleKey
from src.modules.operations.automation.interfaces import IAutomationPolicyQuery
from src.modules.sales.subscriptions.domain.models import SubscriptionModel
from src.modules.sales.subscriptions.infra.mysql import SubscriptionRepository
from src.modules.sales.subscriptions.interfaces import ICustomerHoldCommand


class SubscriptionLifecycleCommand:
    def __init__(
        self,
        repo: SubscriptionRepository,
        provisioning: IProvisioningCommand,
        holds: ICustomerHoldCommand,
    ) -> None:
        self.repo = repo
        self.provisioning = provisioning
        self.holds = holds

    @transactional
    async def check(self, id: int) -> SubscriptionModel:
        subscription = await self.holds.check(id)
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        if subscription.status != "active":
            return subscription
        await self.repo.update_existing(
            subscription, SubscriptionModel.patch(lifecycle_checked_at=now)
        )
        if (
            subscription.expires_at is None or subscription.expires_at > now
        ) and (
            subscription.quota_bytes is None
            or subscription.used_bytes < subscription.quota_bytes
        ):
            return subscription
        completion = (
            "expire"
            if (
                subscription.expires_at is not None
                and subscription.expires_at <= now
            )
            else "quota"
        )
        if subscription.provisioning_managed:
            await self.provisioning.retire(
                subscription.id,
                subscription.renewal_count,
                completion,
                "پایان مدت اشتراک"
                if completion == "expire"
                else "پایان سهمیهٔ اشتراک",
                None,
            )
        else:
            await self.repo.update_existing(
                subscription,
                SubscriptionModel.patch(
                    status="expired" if completion == "expire" else "exhausted"
                ),
            )
        return subscription


class SubscriptionLifecycleQuery:
    def __init__(
        self,
        repo: SubscriptionRepository,
        settings: PapilioSettings,
        automation: IAutomationPolicyQuery,
    ) -> None:
        self.repo = repo
        self.settings = settings
        self.automation = automation

    async def due_ids(self) -> list[int]:
        current = await self.automation.schedule(ScheduleKey.LIFECYCLE)
        if not current.runnable:
            return []
        schedule = current.values
        result = await self.repo.retirement_ids(
            datetime.now(UTC).replace(tzinfo=None),
            schedule.batch_size,
            ["active"],
        )
        return result
