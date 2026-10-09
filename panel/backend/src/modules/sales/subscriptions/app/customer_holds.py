from datetime import UTC, datetime

from papilio.errors.exceptions import ConflictException, NotFoundException
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional

from src.config.settings import PapilioSettings
from src.modules.accounts.customers.domain.models import CustomerModel
from src.modules.accounts.customers.infra.mysql import CustomerRepository
from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.network.provisioning.interfaces import IProvisioningCommand
from src.modules.operations.automation.domain.dtos import ScheduleKey
from src.modules.operations.automation.interfaces import IAutomationPolicyQuery
from src.modules.sales.subscriptions.domain.models import (
    SubscriptionControlModel,
    SubscriptionModel,
)
from src.modules.sales.subscriptions.infra.mysql import (
    SubscriptionControlRepository,
    SubscriptionRepository,
)
from src.modules.sales.subscriptions.infra.readers import CustomerHoldReader


class CustomerHoldCommand:
    def __init__(
        self,
        subscriptions: SubscriptionRepository,
        controls: SubscriptionControlRepository,
        customers: ICustomerService,
        provisioning: IProvisioningCommand,
    ) -> None:
        self.subscriptions = subscriptions
        self.controls = controls
        self.customers = customers
        self.provisioning = provisioning

    @handle_conflicts
    @transactional
    async def check(self, subscription_id: int) -> SubscriptionModel:
        subscription = await self.subscriptions.locked(subscription_id)
        if subscription is None:
            raise NotFoundException(
                message="اشتراک پیدا نشد.",
                message_code="subscription_not_found",
                entity="subscription",
                identifier="id",
                identifier_value=subscription_id,
            )
        customer = await self.customers.locked(subscription.customer_id)
        if (
            customer.services_enabled
            and not customer.service_hold_pending
            or subscription.status
            not in {
                "active",
                "pending_provision",
            }
        ):
            return subscription
        if (
            customer.service_hold_at is None
            or customer.service_hold_clock is None
            or customer.service_hold_reason is None
            or (
                customer.service_hold_by_staff_id is None
                and customer.service_hold_by_reseller_account_id is None
            )
        ):
            raise ConflictException(
                message=("سیاست توقف مشتری ناقص است؛ دسترسی را بازبینی کنید."),
                message_code="customer_hold_policy_missing",
                unique_dict={"id": customer.id},
            )
        key = (
            f"customer_hold:{customer.id}:{customer.service_hold_revision}:"
            f"{subscription.id}:{subscription.renewal_count}"
        )
        prior = await self.controls.by_request(key)
        if prior is not None:
            return subscription
        await self.controls.create(
            SubscriptionControlModel(
                request_key=key,
                subscription_id=subscription.id,
                staff_id=customer.service_hold_by_staff_id,
                actor_account_id=customer.service_hold_by_reseller_account_id,
                action="suspend",
                reason=customer.service_hold_reason,
                clock=customer.service_hold_clock,
            )
        )
        await self.subscriptions.update_existing(
            subscription,
            SubscriptionModel.patch(
                suspended_at=customer.service_hold_at,
                suspension_clock=customer.service_hold_clock,
                suspension_reason=customer.service_hold_reason,
                suspended_by_staff_id=customer.service_hold_by_staff_id,
                suspended_by_reseller_account_id=customer.service_hold_by_reseller_account_id,
                lifecycle_checked_at=datetime.now(UTC).replace(
                    tzinfo=None, microsecond=0
                ),
            ),
        )
        if subscription.provisioning_managed:
            await self.provisioning.retire(
                subscription.id,
                subscription.renewal_count,
                "suspend",
                customer.service_hold_reason,
                customer.service_hold_by_staff_id,
            )
        else:
            await self.subscriptions.update_existing(
                subscription, SubscriptionModel.patch(status="suspended")
            )
        return subscription


class CustomerHoldQuery:
    def __init__(
        self,
        reader: CustomerHoldReader,
        settings: PapilioSettings,
        automation: IAutomationPolicyQuery,
    ) -> None:
        self.reader = reader
        self.settings = settings
        self.automation = automation

    async def due_ids(self) -> list[int]:
        current = await self.automation.schedule(ScheduleKey.CUSTOMER_HOLDS)
        if not current.runnable:
            return []
        schedule = current.values
        candidates = await self.reader.candidates(
            ["active", "pending_provision"],
            False,
            True,
            schedule.batch_size,
        )
        return [candidate.subscription_id for candidate in candidates]


class CustomerHoldFinalizeCommand:
    def __init__(
        self, customers: CustomerRepository, reader: CustomerHoldReader
    ) -> None:
        self.customers = customers
        self.reader = reader

    @transactional
    async def check(self, customer_id: int) -> bool:
        customer = await self.customers.locked(customer_id)
        if customer is None:
            raise NotFoundException(
                message="مشتری پیدا نشد.",
                message_code="customer_not_found",
                entity="customer",
                identifier="id",
                identifier_value=customer_id,
            )
        if not customer.service_hold_pending:
            return True
        outstanding = await self.reader.outstanding_count(
            customer_id, ["active", "pending_provision", "revoking"]
        )
        if outstanding:
            await self.customers.update_row_by_id(
                customer_id,
                CustomerModel.patch(
                    updated_at=datetime.now(UTC).replace(tzinfo=None)
                ),
            )
            return False
        await self.customers.update_row_by_id(
            customer_id, CustomerModel.patch(service_hold_pending=False)
        )
        return True


class CustomerHoldFinalizeQuery:
    def __init__(
        self,
        repo: CustomerRepository,
        settings: PapilioSettings,
        automation: IAutomationPolicyQuery,
    ) -> None:
        self.repo = repo
        self.settings = settings
        self.automation = automation

    async def due_ids(self) -> list[int]:
        current = await self.automation.schedule(ScheduleKey.CUSTOMER_HOLDS)
        if not current.runnable:
            return []
        schedule = current.values
        result = await self.repo.hold_pending_ids(True, schedule.batch_size)
        return result
