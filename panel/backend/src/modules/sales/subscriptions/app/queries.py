from datetime import UTC, datetime

from src.config.settings import PapilioSettings
from src.modules.operations.automation.domain.dtos import ScheduleKey
from src.modules.operations.automation.interfaces import IAutomationPolicyQuery
from src.modules.sales.subscriptions.infra.mysql import SubscriptionRepository


class RenewalQuery:
    def __init__(
        self,
        subscriptions: SubscriptionRepository,
        settings: PapilioSettings,
        automation: IAutomationPolicyQuery,
    ) -> None:
        self.subscriptions = subscriptions
        self.settings = settings
        self.automation = automation

    async def due_ids(self) -> list[int]:
        current = await self.automation.schedule(ScheduleKey.RENEWALS)
        if not current.runnable:
            return []
        schedule = current.values
        now = datetime.now(UTC).replace(tzinfo=None)
        result = await self.subscriptions.due_ids(
            now,
            schedule.batch_size,
            True,
            ["active", "expired", "exhausted"],
            include_quota=True,
        )
        return result
