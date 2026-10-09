import asyncio

from papilio.errors.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
    UnAuthorizedException,
    ValidationException,
)
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import hash_sha256

from src.modules.accounts.customers.infra.mysql import CustomerRepository
from src.modules.operations.notifications.domain.dtos import (
    NotificationEvent,
    NotificationKind,
)
from src.modules.operations.notifications.interfaces import (
    INotificationCreateCommand,
)
from src.modules.support.app.queries import missing_ticket
from src.modules.support.domain.dtos import (
    ClosedReplyMode,
    TicketCreate,
    TicketReply,
    TicketStateWrite,
    TicketStatus,
)
from src.modules.support.domain.models import (
    SupportMessageModel,
    SupportStateChangeModel,
    SupportTicketModel,
)
from src.modules.support.domain.results import SupportAvailability
from src.modules.support.infra.mysql import (
    SupportMessageRepository,
    SupportStateChangeRepository,
    SupportTicketRepository,
)
from src.modules.support.infra.readers import SupportContextReader
from src.modules.support.interfaces import ISupportPolicyQuery


class SupportCreateCommand:
    def __init__(
        self,
        tickets: SupportTicketRepository,
        messages: SupportMessageRepository,
        customers: CustomerRepository,
        contexts: SupportContextReader,
        policy: ISupportPolicyQuery,
        notifications: INotificationCreateCommand,
    ) -> None:
        self.tickets = tickets
        self.messages = messages
        self.customers = customers
        self.contexts = contexts
        self.policy = policy
        self.notifications = notifications

    @handle_conflicts
    @transactional
    async def create(
        self, customer_id: int, data: TicketCreate, staff_id: int | None = None
    ) -> SupportTicketModel:
        customer = await self.customers.locked(customer_id)
        if customer is None:
            raise missing_customer(customer_id)
        if staff_id is None and not customer.is_active:
            raise denied_customer()
        existing = await self.tickets.by_request(customer_id, data.request_key)
        if existing is not None:
            if (
                existing.creation_hash
                != (
                    await asyncio.to_thread(
                        hash_sha256, data.model_dump_json()
                    )
                )
                or existing.created_by_staff_id != staff_id
            ):
                raise conflict("support_request_reused", existing.id)
            return existing
        availability = await self.policy.current()
        require_capacity(availability)
        policy = availability.values
        if not policy.new_tickets_enabled:
            raise forbidden("support_new_disabled")
        if len(data.body) > policy.max_message_chars:
            raise conflict("support_message_length", customer_id)
        if data.subscription_id is not None:
            owner = await self.contexts.subscription_owner(
                data.subscription_id
            )
            if owner != customer_id:
                raise conflict("support_context_unavailable", customer_id)
        if data.topup_id is not None:
            owner = await self.contexts.topup_owner(data.topup_id)
            if owner != customer_id:
                raise conflict("support_context_unavailable", customer_id)
        status = (
            policy.staff_reply_status
            if staff_id is not None
            else TicketStatus.OPEN
        )
        if status != TicketStatus.CLOSED:
            open_ids = await self.tickets.open_ids(
                customer_id, TicketStatus.CLOSED, policy.max_open_tickets
            )
            if len(open_ids) >= policy.max_open_tickets:
                raise conflict("support_open_capacity", customer_id)
        ticket = await self.tickets.create(
            SupportTicketModel(
                customer_id=customer_id,
                created_by_staff_id=staff_id,
                request_key=data.request_key,
                creation_hash=(
                    await asyncio.to_thread(
                        hash_sha256, data.model_dump_json()
                    )
                ),
                subject=data.subject,
                subscription_id=data.subscription_id,
                topup_id=data.topup_id,
                status=status,
                revision=1,
            )
        )
        await self.messages.create(
            SupportMessageModel(
                ticket_id=ticket.id,
                revision=1,
                request_key=data.request_key,
                body=data.body,
                staff_id=staff_id,
                customer_id=customer_id if staff_id is None else None,
            )
        )
        if staff_id is not None:
            await self.notifications.enqueue(
                customer_id,
                NotificationEvent(
                    event_key=f"support:{ticket.id}:1",
                    kind=NotificationKind.SUPPORT_REPLY,
                    status="پاسخ پشتیبانی",
                    record_id=ticket.id,
                ),
            )
        return ticket


class SupportThreadCommand:
    def __init__(
        self,
        tickets: SupportTicketRepository,
        messages: SupportMessageRepository,
        history: SupportStateChangeRepository,
        customers: CustomerRepository,
        policy: ISupportPolicyQuery,
        notifications: INotificationCreateCommand,
    ) -> None:
        self.tickets = tickets
        self.messages = messages
        self.history = history
        self.customers = customers
        self.policy = policy
        self.notifications = notifications

    @handle_conflicts
    @transactional
    async def reply(
        self,
        id: int,
        data: TicketReply,
        customer_id: int | None = None,
        staff_id: int | None = None,
    ) -> SupportTicketModel:
        ticket = await self.locked_ticket(id, customer_id)
        require_actor(customer_id, staff_id)
        existing = await self.messages.by_request(id, data.request_key)
        if existing is not None:
            if (
                existing.body != data.body
                or existing.customer_id != customer_id
                or existing.staff_id != staff_id
            ):
                raise conflict("support_request_reused", id)
            return ticket
        availability = await self.policy.current()
        require_capacity(availability)
        policy = availability.values
        if (
            customer_id is not None and not policy.customer_replies_enabled
        ) or (staff_id is not None and not policy.staff_replies_enabled):
            raise forbidden("support_reply_disabled")
        if len(data.body) > policy.max_message_chars:
            raise conflict("support_message_length", id)
        if ticket.revision != data.expected_revision:
            raise conflict("support_ticket_changed", id)
        status = (
            policy.staff_reply_status
            if staff_id is not None
            else TicketStatus.OPEN
        )
        if ticket.status == TicketStatus.CLOSED:
            if policy.closed_reply_mode == ClosedReplyMode.REJECT:
                raise conflict("support_ticket_closed", id)
            if status != TicketStatus.CLOSED:
                open_ids = await self.tickets.open_ids(
                    ticket.customer_id,
                    TicketStatus.CLOSED,
                    policy.max_open_tickets,
                )
                if len(open_ids) >= policy.max_open_tickets:
                    raise conflict("support_open_capacity", id)
        ids = await self.messages.ids(id, policy.max_messages_per_ticket)
        if len(ids) >= policy.max_messages_per_ticket:
            raise conflict("support_thread_capacity", id)
        revision = ticket.revision + 1
        await self.messages.create(
            SupportMessageModel(
                ticket_id=id,
                revision=revision,
                request_key=data.request_key,
                body=data.body,
                customer_id=customer_id,
                staff_id=staff_id,
            )
        )
        await self.history.create(
            SupportStateChangeModel(
                ticket_id=id,
                revision=revision,
                previous_status=ticket.status,
                status=status,
                reason="پاسخ مدیر" if staff_id is not None else "پیام مشتری",
                customer_id=customer_id,
                staff_id=staff_id,
            )
        )
        await self.tickets.update_row_by_id(
            id, SupportTicketModel.patch(status=status, revision=revision)
        )
        result = await self.tickets.locked(id)
        assert result is not None
        if staff_id is not None:
            await self.notifications.enqueue(
                result.customer_id,
                NotificationEvent(
                    event_key=f"support:{id}:{revision}",
                    kind=NotificationKind.SUPPORT_REPLY,
                    status="پاسخ پشتیبانی",
                    record_id=id,
                ),
            )
        return result

    @handle_conflicts
    @transactional
    async def state(
        self,
        id: int,
        data: TicketStateWrite,
        customer_id: int | None = None,
        staff_id: int | None = None,
    ) -> SupportTicketModel:
        ticket = await self.locked_ticket(id, customer_id)
        require_actor(customer_id, staff_id)
        availability = await self.policy.current()
        policy = availability.values
        if customer_id is not None:
            if (
                data.status == TicketStatus.WAITING_CUSTOMER
                or data.status == TicketStatus.CLOSED
                and not policy.customer_closure_enabled
                or data.status == TicketStatus.OPEN
                and not policy.customer_reopen_enabled
            ):
                raise forbidden("support_state_denied")
        if ticket.revision != data.expected_revision:
            raise conflict("support_ticket_changed", id)
        if ticket.status == data.status:
            return ticket
        if (
            ticket.status == TicketStatus.CLOSED
            and data.status != TicketStatus.CLOSED
        ):
            require_capacity(availability)
            ids = await self.tickets.open_ids(
                ticket.customer_id,
                TicketStatus.CLOSED,
                policy.max_open_tickets,
            )
            if len(ids) >= policy.max_open_tickets:
                raise conflict("support_open_capacity", id)
        revision = ticket.revision + 1
        await self.history.create(
            SupportStateChangeModel(
                ticket_id=id,
                revision=revision,
                previous_status=ticket.status,
                status=data.status,
                reason=data.reason,
                customer_id=customer_id,
                staff_id=staff_id,
            )
        )
        await self.tickets.update_row_by_id(
            id, SupportTicketModel.patch(status=data.status, revision=revision)
        )
        result = await self.tickets.locked(id)
        assert result is not None
        return result

    async def locked_ticket(
        self, id: int, customer_id: int | None
    ) -> SupportTicketModel:
        context = await self.tickets.get_by_id(id)
        if (
            context is None
            or customer_id is not None
            and context.customer_id != customer_id
        ):
            raise missing_ticket(id)
        customer = await self.customers.locked(context.customer_id)
        if customer is None:
            raise missing_customer(context.customer_id)
        if customer_id is not None and not customer.is_active:
            raise denied_customer()
        ticket = await self.tickets.locked(id)
        if (
            ticket is None
            or customer_id is not None
            and ticket.customer_id != customer_id
        ):
            raise missing_ticket(id)
        return ticket


def require_actor(customer_id: int | None, staff_id: int | None) -> None:
    if (customer_id is None) == (staff_id is None):
        raise forbidden("support_actor_denied")


def require_capacity(availability: SupportAvailability) -> None:
    if not availability.capacity_valid:
        raise ValidationException(
            message="سیاست پشتیبانی از ظرفیت تنظیم‌شده بیشتر است.",
            message_code="support_policy_capacity",
            loc=["support"],
            input=availability.values.model_dump(),
            ctx={},
        )


def conflict(code: str, id: int) -> ConflictException:
    return ConflictException(
        message="درخواست پشتیبانی با وضعیت یا سیاست فعلی سازگار نیست.",
        message_code=code,
        unique_dict={"id": id},
    )


def forbidden(code: str) -> ForbiddenException:
    return ForbiddenException(
        message="این عملیات پشتیبانی در دسترس نیست.", message_code=code
    )


def missing_customer(id: int) -> NotFoundException:
    return NotFoundException(
        message="حساب مشتری پیدا نشد.",
        message_code="customer_not_found",
        entity="customer",
        identifier="id",
        identifier_value=id,
    )


def denied_customer() -> UnAuthorizedException:
    return UnAuthorizedException(
        message="حساب مشتری معتبر نیست.", message_code="customer_unauthorized"
    )
