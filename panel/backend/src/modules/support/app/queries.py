from papilio.errors.exceptions import NotFoundException

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.operations.preferences.interfaces import IPreferencesService
from src.modules.support.domain.dtos import (
    CustomerTicketSearch,
    ThreadSearch,
    TicketSearch,
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


class SupportPolicyQuery:
    def __init__(
        self, preferences: IPreferencesService, settings: PapilioSettings
    ) -> None:
        self.preferences = preferences
        self.settings = settings

    async def current(self) -> SupportAvailability:
        current = await self.preferences.current()
        policy = current.values.support
        assert policy is not None
        capacity = self.settings.support
        return SupportAvailability(
            policy,
            policy.max_open_tickets <= capacity.max_open_tickets
            and policy.max_messages_per_ticket
            <= capacity.max_messages_per_ticket
            and policy.max_message_chars <= capacity.max_message_chars,
        )


class SupportTicketQuery:
    def __init__(
        self, repo: SupportTicketRepository, settings: PapilioSettings
    ) -> None:
        self.repo = repo
        self.settings = settings

    async def get(self, id: int) -> SupportTicketModel:
        result = await self.repo.get_by_id(id)
        if result is None:
            raise missing_ticket(id)
        return result

    async def get_for_customer(
        self, id: int, customer_id: int
    ) -> SupportTicketModel:
        result = await self.repo.owned(id, customer_id)
        if result is None:
            raise missing_ticket(id)
        return result

    async def search(
        self, data: TicketSearch
    ) -> ServicePage[SupportTicketModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page(
            data.q,
            data.status,
            data.customer_id,
            (data.page - 1) * limit,
            limit,
        )
        return service_page(result, limit)

    async def search_customer(
        self, customer_id: int, data: CustomerTicketSearch
    ) -> ServicePage[SupportTicketModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.customer_page(
            customer_id, data.q, data.status, (data.page - 1) * limit, limit
        )
        return service_page(result, limit)


class SupportMessageQuery:
    def __init__(
        self, repo: SupportMessageRepository, settings: PapilioSettings
    ) -> None:
        self.repo = repo
        self.settings = settings

    async def search(
        self, id: int, data: ThreadSearch
    ) -> ServicePage[SupportMessageModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page(id, (data.page - 1) * limit, limit)
        return service_page(result, limit)


class SupportHistoryQuery:
    def __init__(
        self, repo: SupportStateChangeRepository, settings: PapilioSettings
    ) -> None:
        self.repo = repo
        self.settings = settings

    async def search(
        self, id: int, data: ThreadSearch
    ) -> ServicePage[SupportStateChangeModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page(id, (data.page - 1) * limit, limit)
        return service_page(result, limit)


def missing_ticket(id: int) -> NotFoundException:
    return NotFoundException(
        message="تیکت در این حساب پیدا نشد.",
        message_code="support_ticket_not_found",
        entity="support_ticket",
        identifier="id",
        identifier_value=id,
    )
