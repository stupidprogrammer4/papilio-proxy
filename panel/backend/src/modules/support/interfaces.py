from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.support.domain.dtos import (
    CustomerTicketSearch,
    ThreadSearch,
    TicketCreate,
    TicketReply,
    TicketSearch,
    TicketStateWrite,
)
from src.modules.support.domain.models import (
    SupportMessageModel,
    SupportStateChangeModel,
    SupportTicketModel,
)
from src.modules.support.domain.results import SupportAvailability


class ISupportPolicyQuery(Protocol):
    def current(self) -> Awaitable[SupportAvailability]: ...


class ISupportTicketQuery(Protocol):
    def get(self, id: int) -> Awaitable[SupportTicketModel]: ...
    def get_for_customer(
        self, id: int, customer_id: int
    ) -> Awaitable[SupportTicketModel]: ...
    def search(
        self, data: TicketSearch
    ) -> Awaitable[ServicePage[SupportTicketModel]]: ...
    def search_customer(
        self, customer_id: int, data: CustomerTicketSearch
    ) -> Awaitable[ServicePage[SupportTicketModel]]: ...


class ISupportMessageQuery(Protocol):
    def search(
        self, id: int, data: ThreadSearch
    ) -> Awaitable[ServicePage[SupportMessageModel]]: ...


class ISupportHistoryQuery(Protocol):
    def search(
        self, id: int, data: ThreadSearch
    ) -> Awaitable[ServicePage[SupportStateChangeModel]]: ...


class ISupportCreateCommand(Protocol):
    def create(
        self, customer_id: int, data: TicketCreate, staff_id: int | None = None
    ) -> Awaitable[SupportTicketModel]: ...


class ISupportThreadCommand(Protocol):
    def reply(
        self,
        id: int,
        data: TicketReply,
        customer_id: int | None = None,
        staff_id: int | None = None,
    ) -> Awaitable[SupportTicketModel]: ...
    def state(
        self,
        id: int,
        data: TicketStateWrite,
        customer_id: int | None = None,
        staff_id: int | None = None,
    ) -> Awaitable[SupportTicketModel]: ...
