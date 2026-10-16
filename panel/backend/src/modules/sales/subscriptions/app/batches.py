"""Batch persistence capabilities for subscription-owned facts."""

from papilio.errors.exceptions import NotFoundException

from src.modules.sales.subscriptions.domain.models import SubscriptionModel
from src.modules.sales.subscriptions.domain.results import (
    SubscriptionProvisioningActivation,
    SubscriptionUsageUpdate,
)
from src.modules.sales.subscriptions.infra.mysql import SubscriptionRepository


class SubscriptionBatchService:
    def __init__(self, repo: SubscriptionRepository) -> None:
        self.repo = repo

    async def by_ids_many(self, ids: list[int]) -> list[SubscriptionModel]:
        result = await self.repo.by_ids_many(ids)
        return result

    async def locked_many(self, ids: list[int]) -> list[SubscriptionModel]:
        selected = sorted(set(ids))
        rows = await self.repo.locked_many(selected)
        row_ids = {row.id for row in rows}
        missing = next(
            (item for item in selected if item not in row_ids), None
        )
        if missing is not None:
            raise NotFoundException(
                message="Subscription not found.",
                message_code="subscription_not_found",
                entity="subscription",
                identifier="id",
                identifier_value=missing,
            )
        return rows

    async def update_used_many(
        self, updates: list[SubscriptionUsageUpdate]
    ) -> None:
        await self.repo.update_used_many(updates)

    async def activate_provisioned_many(
        self, updates: list[SubscriptionProvisioningActivation]
    ) -> None:
        await self.repo.activate_provisioned_many(updates)
