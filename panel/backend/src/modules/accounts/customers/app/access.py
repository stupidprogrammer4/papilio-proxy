from datetime import UTC, datetime

from papilio.errors.exceptions import ConflictException, NotFoundException
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.accounts.customer_auth.interfaces import ICustomerAuthCommand
from src.modules.accounts.customers.domain.dtos import (
    CustomerAccessSearch,
    CustomerAccessState,
    CustomerAccessWrite,
)
from src.modules.accounts.customers.domain.models import (
    CustomerAccessChangeModel,
    CustomerModel,
)
from src.modules.accounts.customers.domain.results import (
    CustomerAccessActor,
    ResellerCustomerAccessActor,
    StaffCustomerAccessActor,
)
from src.modules.accounts.customers.infra.mysql import (
    CustomerAccessChangeRepository,
    CustomerRepository,
)
from src.modules.accounts.customers.interfaces import ICustomerService


class CustomerAccessCommand:
    def __init__(
        self,
        customers: CustomerRepository,
        changes: CustomerAccessChangeRepository,
        authentication: ICustomerAuthCommand,
    ) -> None:
        self.customers = customers
        self.changes = changes
        self.authentication = authentication

    @handle_conflicts
    @transactional
    async def update(
        self, id: int, data: CustomerAccessWrite, actor: CustomerAccessActor
    ) -> CustomerModel:
        customer = await self.customers.locked(id)
        if customer is None:
            raise missing(id)
        staff_id = (
            actor.staff_id
            if isinstance(actor, StaffCustomerAccessActor)
            else None
        )
        account_id = (
            actor.account_id
            if isinstance(actor, ResellerCustomerAccessActor)
            else None
        )
        reseller_id = (
            actor.reseller_id
            if isinstance(actor, ResellerCustomerAccessActor)
            else None
        )
        key = (
            f"{staff_id}:{data.request_key}"
            if staff_id is not None
            else f"reseller:{reseller_id}:{account_id}:{data.request_key}"
        )
        prior = await self.changes.by_request(key)
        if prior is not None:
            if (
                prior.customer_id != id
                or CustomerAccessState.model_validate_json(prior.values_json)
                != data.values
                or prior.reason != data.reason
                or prior.clock != data.clock
            ):
                raise conflict("customer_access_key_reused", id)
            return customer
        current = CustomerAccessState(
            is_active=customer.is_active,
            services_enabled=customer.services_enabled,
            renewals_enabled=customer.renewals_enabled,
        )
        if current != data.expected:
            raise conflict("customer_access_changed", id)
        if current == data.values:
            return customer
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        await self.changes.create(
            CustomerAccessChangeModel(
                request_key=key,
                customer_id=id,
                staff_id=staff_id,
                reseller_id=reseller_id,
                actor_account_id=account_id,
                previous_json=current.model_dump_json(),
                values_json=data.values.model_dump_json(),
                reason=data.reason,
                clock=data.clock,
            )
        )
        stopping = (
            customer.services_enabled and not data.values.services_enabled
        )
        if (
            not customer.services_enabled
            and not data.values.services_enabled
            and customer.service_hold_clock != data.clock
        ):
            raise conflict("customer_hold_clock_changed", id)
        await self.customers.update_row_by_id(
            id,
            CustomerModel.patch(
                service_hold_pending=customer.service_hold_pending or stopping,
                service_hold_revision=customer.service_hold_revision + 1
                if stopping
                else customer.service_hold_revision,
                is_active=data.values.is_active,
                services_enabled=data.values.services_enabled,
                renewals_enabled=data.values.renewals_enabled,
                service_hold_at=now
                if stopping
                else None
                if data.values.services_enabled
                and not customer.service_hold_pending
                else customer.service_hold_at,
                service_hold_clock=data.clock
                if stopping
                else customer.service_hold_clock
                if customer.service_hold_pending
                else data.clock,
                service_hold_reason=data.reason
                if stopping
                else None
                if data.values.services_enabled
                and not customer.service_hold_pending
                else customer.service_hold_reason,
                service_hold_by_reseller_account_id=account_id
                if stopping
                else None
                if data.values.services_enabled
                and not customer.service_hold_pending
                else customer.service_hold_by_reseller_account_id,
                service_hold_by_staff_id=staff_id
                if stopping
                else None
                if data.values.services_enabled
                and not customer.service_hold_pending
                else customer.service_hold_by_staff_id,
            ),
        )
        if not data.values.is_active:
            await self.authentication.revoke_customer(id)
        result = await self.customers.locked(id)
        assert result is not None
        return result


class CustomerAccessQuery:
    def __init__(
        self,
        repo: CustomerAccessChangeRepository,
        customers: ICustomerService,
        settings: PapilioSettings,
    ) -> None:
        self.repo = repo
        self.customers = customers
        self.settings = settings

    async def search(
        self, customer_id: int, data: CustomerAccessSearch
    ) -> ServicePage[CustomerAccessChangeModel]:
        await self.customers.get(customer_id)
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page(
            customer_id, (data.page - 1) * limit, limit
        )
        return service_page(result, limit)


def missing(id: int) -> NotFoundException:
    return NotFoundException(
        message="مشتری پیدا نشد.",
        message_code="customer_not_found",
        entity="customer",
        identifier="id",
        identifier_value=id,
    )


def conflict(code: str, id: int) -> ConflictException:
    return ConflictException(
        message="وضعیت دسترسی مشتری با درخواست سازگار نیست.",
        message_code=code,
        unique_dict={"id": id},
    )
