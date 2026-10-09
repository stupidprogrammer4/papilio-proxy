from papilio.errors.exceptions import NotFoundException
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.accounts.customers.domain.dtos import (
    CustomerAccessState,
    CustomerCreate,
    CustomerProfileWrite,
    CustomerSearch,
)
from src.modules.accounts.customers.domain.models import CustomerModel
from src.modules.accounts.customers.infra.mysql import CustomerRepository
from src.modules.operations.preferences.interfaces import IPreferencesService


class CustomerService:
    def __init__(
        self,
        repo: CustomerRepository,
        settings: PapilioSettings,
        preferences: IPreferencesService,
    ) -> None:
        self.repo = repo
        self.settings = settings
        self.preferences = preferences

    async def creation_access(self) -> CustomerAccessState:
        snapshot = await self.preferences.current()
        result = snapshot.values.customer_creation_access
        assert result is not None
        return result

    @handle_conflicts
    @transactional
    async def create(self, data: CustomerCreate) -> CustomerModel:
        choice = data.access or await self.creation_access()
        result = await self.repo.create(
            CustomerModel(
                display_name=data.display_name,
                telegram_id=data.telegram_id,
                is_active=choice.is_active,
                services_enabled=choice.services_enabled,
                renewals_enabled=choice.renewals_enabled,
            )
        )
        return result

    async def get(self, id: int) -> CustomerModel:
        result = await self.repo.get_by_id(id)
        if result is None:
            raise NotFoundException(
                message="مشتری پیدا نشد.",
                message_code="customer_not_found",
                entity="customer",
                identifier="id",
                identifier_value=id,
            )
        return result

    async def locked(self, id: int) -> CustomerModel:
        result = await self.repo.locked(id)
        if result is None:
            raise NotFoundException(
                message="مشتری پیدا نشد.",
                message_code="customer_not_found",
                entity="customer",
                identifier="id",
                identifier_value=id,
            )
        return result

    async def locked_many(self, ids: list[int]) -> list[CustomerModel]:
        selected = sorted(set(ids))
        if not selected:
            return []
        rows = await self.repo.locked_many(selected, ascending=True)
        if len(rows) != len(selected):
            missing = next(
                id for id in selected if id not in {row.id for row in rows}
            )
            raise NotFoundException(
                message="Customer not found",
                message_code="customer_not_found",
                entity="customer",
                identifier="id",
                identifier_value=missing,
            )
        return rows

    @transactional
    async def update_profile(
        self, id: int, data: CustomerProfileWrite
    ) -> CustomerModel:
        await self.get(id)
        await self.repo.update_row_by_id(
            id, CustomerModel.patch(display_name=data.display_name)
        )
        result = await self.get(id)
        return result

    @transactional
    async def ensure_telegram(
        self, telegram_id: int, display_name: str
    ) -> CustomerModel:
        choice = await self.creation_access()
        result = await self.repo.ensure_telegram(
            CustomerModel(
                telegram_id=telegram_id,
                display_name=display_name,
                is_active=choice.is_active,
                services_enabled=choice.services_enabled,
                renewals_enabled=choice.renewals_enabled,
            )
        )
        return result

    async def search(self, data: CustomerSearch) -> ServicePage[CustomerModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.repo.page(data.q, (data.page - 1) * limit, limit)
        return service_page(result, limit)
