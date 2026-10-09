from papilio.errors.exceptions import ConflictException
from papilio.infra.db.tools.decorators import transactional

from src.config.settings import PapilioSettings
from src.modules.operations.notifications.domain.dtos import (
    NotificationEvent,
    NotificationKind,
)
from src.modules.operations.notifications.interfaces import (
    INotificationCreateCommand,
)
from src.modules.sales.loyalty.domain.models import PurchaseVolumeModel
from src.modules.sales.loyalty.domain.results import CustomerPriceQuote
from src.modules.sales.loyalty.infra.mysql import PurchaseVolumeRepository
from src.modules.sales.loyalty.interfaces import (
    ICustomerLoyaltyQuery,
    ILoyaltyPolicyService,
)


class PurchaseVolumeCommand:
    def __init__(
        self,
        repo: PurchaseVolumeRepository,
        policy: ILoyaltyPolicyService,
        loyalty: ICustomerLoyaltyQuery,
        notifications: INotificationCreateCommand,
        settings: PapilioSettings,
    ) -> None:
        (
            self.repo,
            self.policy,
            self.loyalty,
            self.notifications,
            self.settings,
        ) = repo, policy, loyalty, notifications, settings

    @transactional
    async def record(
        self,
        customer_id: int,
        subscription_id: int,
        generation: int,
        plan_id: int,
        quota_bytes: int | None,
        paid_rial: int,
        commerce: CustomerPriceQuote | None = None,
    ) -> None:
        if self.settings.loyalty is None:
            return
        reference = f"volume:{subscription_id}:{generation}"
        existing = await self.repo.by_reference(reference)
        if existing is not None:
            if (
                existing.customer_id != customer_id
                or existing.subscription_id != subscription_id
                or existing.generation != generation
                or existing.paid_rial != paid_rial
            ):
                raise ConflictException(
                    message="Purchase credit identity changed",
                    message_code="purchase_volume_reused",
                    unique_dict={"reference": reference},
                )
            return
        policy = (await self.policy.current()).values
        if not policy.enabled or paid_rial < policy.minimum_qualifying_rial:
            return
        before = await self.loyalty.status(customer_id, locked=True)
        volume = (
            quota_bytes
            if quota_bytes is not None
            else policy.unlimited_plan_bytes.get(
                plan_id, policy.unlimited_equivalent_bytes
            )
            if policy.unlimited_credit_mode == "equivalent"
            else 0
        )
        await self.repo.create(
            PurchaseVolumeModel(
                reference=reference,
                customer_id=customer_id,
                subscription_id=subscription_id,
                generation=generation,
                volume_bytes=volume,
                purchase_count=1 if generation == 0 else 0,
                paid_rial=paid_rial,
                commerce_json=commerce.model_dump_json()
                if commerce is not None
                else None,
            )
        )
        after = await self.loyalty.status(customer_id, locked=True)
        if (
            policy.notify_tier_changes
            and after.tier is not None
            and (before.tier is None or before.tier.id != after.tier.id)
        ):
            await self.notifications.enqueue(
                customer_id,
                NotificationEvent(
                    event_key=f"tier:{subscription_id}:{generation}:purchase",
                    kind=NotificationKind.TIER_CHANGED,
                    record_id=subscription_id,
                    status=after.tier.code,
                ),
            )

    @transactional
    async def reverse(self, subscription_id: int, generation: int) -> None:
        reference = f"volume-refund:{subscription_id}:{generation}"
        if await self.repo.by_reference(reference) is not None:
            return
        original = await self.repo.by_reference(
            f"volume:{subscription_id}:{generation}"
        )
        if original is None:
            return
        policy = (
            (await self.policy.current()).values
            if self.settings.loyalty is not None
            else None
        )
        before = (
            await self.loyalty.status(original.customer_id, locked=True)
            if policy is not None
            and policy.enabled
            and policy.notify_tier_changes
            else None
        )
        await self.repo.create(
            PurchaseVolumeModel(
                reference=reference,
                customer_id=original.customer_id,
                subscription_id=subscription_id,
                generation=generation,
                volume_bytes=-original.volume_bytes,
                purchase_count=-original.purchase_count,
                paid_rial=-original.paid_rial,
                commerce_json=original.commerce_json,
                reverses_id=original.id,
            )
        )

        if policy is None or before is None:
            return
        after = await self.loyalty.status(original.customer_id, locked=True)
        if (
            policy.notify_tier_changes
            and after.tier is not None
            and (before.tier is None or before.tier.id != after.tier.id)
        ):
            await self.notifications.enqueue(
                original.customer_id,
                NotificationEvent(
                    event_key=f"tier:{subscription_id}:{generation}:refund",
                    kind=NotificationKind.TIER_CHANGED,
                    record_id=subscription_id,
                    status=after.tier.code,
                ),
            )
