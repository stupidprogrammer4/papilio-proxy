from datetime import UTC, datetime, timedelta

from papilio.errors.exceptions import ConflictException, NotFoundException
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional

from src.modules.accounts.customers.app.policies import CustomerAccessPolicy
from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.network.provisioning.interfaces import IProvisioningCommand
from src.modules.sales.subscriptions.domain.dtos import (
    SubscriptionResume,
    SubscriptionSuspend,
)
from src.modules.sales.subscriptions.domain.models import (
    SubscriptionControlModel,
    SubscriptionModel,
)
from src.modules.sales.subscriptions.infra.mysql import (
    SubscriptionControlRepository,
    SubscriptionRepository,
)


class SubscriptionControlCommand:
    def __init__(
        self,
        subscriptions: SubscriptionRepository,
        provisioning: IProvisioningCommand,
        controls: SubscriptionControlRepository,
        customers: ICustomerService,
    ) -> None:
        self.subscriptions = subscriptions
        self.provisioning = provisioning
        self.controls = controls
        self.customers = customers

    @handle_conflicts
    @transactional
    async def suspend(
        self, id: int, data: SubscriptionSuspend, staff_id: int
    ) -> SubscriptionModel:
        subscription = await self.subscriptions.locked(id)
        if subscription is None:
            raise missing(id)
        key = f"suspend:{staff_id}:{data.request_key}"
        replay = await self.controls.by_request(key)
        if replay is not None:
            verify_replay(replay, id, data.reason, data.clock)
            return subscription
        if (
            subscription.status in {"suspended", "revoking"}
            and subscription.suspended_at is not None
        ):
            if (
                subscription.suspension_clock != data.clock
                or subscription.suspension_reason != data.reason
            ):
                raise conflict("subscription_suspension_changed", id)
            raise conflict("subscription_suspend_unavailable", id)
        if subscription.status != "active":
            raise conflict("subscription_suspend_unavailable", id)
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        await self.controls.create(
            SubscriptionControlModel(
                request_key=key,
                subscription_id=id,
                staff_id=staff_id,
                action="suspend",
                reason=data.reason,
                clock=data.clock,
            )
        )
        await self.subscriptions.update_existing(
            subscription,
            SubscriptionModel.patch(
                suspended_at=now,
                suspension_clock=data.clock,
                suspension_reason=data.reason,
                suspended_by_staff_id=staff_id,
                suspended_by_reseller_account_id=None,
            ),
        )
        if subscription.provisioning_managed:
            await self.provisioning.retire(
                id,
                subscription.renewal_count,
                "suspend",
                data.reason,
                staff_id,
            )
        else:
            await self.subscriptions.update_existing(
                subscription, SubscriptionModel.patch(status="suspended")
            )
        return subscription

    @handle_conflicts
    @transactional
    async def resume(
        self, id: int, data: SubscriptionResume, staff_id: int
    ) -> SubscriptionModel:
        subscription = await self.subscriptions.locked(id)
        if subscription is None:
            raise missing(id)
        key = f"resume:{staff_id}:{data.request_key}"
        replay = await self.controls.by_request(key)
        if replay is not None:
            verify_replay(replay, id, data.reason, None)
            return subscription
        if (
            subscription.status != "suspended"
            or subscription.suspended_at is None
        ):
            raise conflict("subscription_resume_unavailable", id)
        customer = await self.customers.locked(subscription.customer_id)
        if not CustomerAccessPolicy.services_available(customer):
            raise conflict("customer_services_disabled", id)
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        expiry = (
            None
            if subscription.expires_at is None
            else subscription.expires_at
            + (
                max(now - subscription.suspended_at, timedelta())
                if subscription.suspension_clock == "pause"
                else timedelta()
            )
        )
        if (expiry is not None and expiry <= now) or (
            subscription.quota_bytes is not None
            and subscription.used_bytes >= subscription.quota_bytes
        ):
            raise conflict("subscription_resume_consumed", id)
        await self.controls.create(
            SubscriptionControlModel(
                request_key=key,
                subscription_id=id,
                staff_id=staff_id,
                action="resume",
                reason=data.reason,
                clock=subscription.suspension_clock,
            )
        )
        result = await self.subscriptions.update_existing(
            subscription,
            SubscriptionModel.patch(
                status="pending_provision"
                if subscription.provisioning_managed
                else "active",
                expires_at=expiry,
                suspended_at=None,
                suspension_clock=None,
                suspension_reason=None,
                suspended_by_staff_id=None,
                suspended_by_reseller_account_id=None,
            ),
        )
        if subscription.provisioning_managed:
            await self.provisioning.resume(
                id, subscription.renewal_count, data.reason, staff_id
            )
        return result


def missing(id: int) -> NotFoundException:
    return NotFoundException(
        message="اشتراک پیدا نشد.",
        message_code="subscription_not_found",
        entity="subscription",
        identifier="id",
        identifier_value=id,
    )


def conflict(code: str, id: int) -> ConflictException:
    return ConflictException(
        message="عملیات تعلیق یا ادامه با وضعیت اشتراک سازگار نیست.",
        message_code=code,
        unique_dict={"id": id},
    )


def verify_replay(
    record: SubscriptionControlModel, id: int, reason: str, clock: str | None
) -> None:
    if (
        record.subscription_id != id
        or record.reason != reason
        or record.action == "suspend"
        and record.clock != clock
    ):
        raise conflict("subscription_control_key_reused", id)
