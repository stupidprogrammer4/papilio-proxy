from papilio.errors.exceptions import NotFoundException
from papilio.infra.db.tools.decorators import transactional

from src.config.pagination import ServicePage, page_size
from src.config.settings import PapilioSettings
from src.modules.sales.checkout.app.errors import checkout_missing
from src.modules.sales.checkout.domain.contracts import (
    CheckoutLookup,
    CheckoutRead,
    CheckoutSearch,
)
from src.modules.sales.checkout.infra.mysql import CheckoutIntentRepository


class CheckoutQuery:
    def __init__(
        self, intents: CheckoutIntentRepository, settings: PapilioSettings
    ) -> None:
        self.intents, self.settings = intents, settings

    @transactional
    async def get(self, customer_id: int, id: int) -> CheckoutRead:
        row = await self.intents.owned_current(id, customer_id)
        if row is None:
            raise checkout_missing(id)
        return CheckoutRead.model_validate(row, from_attributes=True)

    async def search(
        self, customer_id: int, data: CheckoutSearch
    ) -> ServicePage[CheckoutRead]:
        limit = page_size(self.settings, data.per_page)
        rows = await self.intents.page_owned(
            customer_id, data.state, (data.page - 1) * limit, limit
        )
        return ServicePage(
            items=[
                CheckoutRead.model_validate(row, from_attributes=True)
                for row in rows.items
            ],
            total_items=rows.total_items,
            per_page=limit,
        )

    @transactional
    async def lookup(
        self, customer_id: int, data: CheckoutLookup
    ) -> CheckoutRead:
        row = await self.intents.by_request_key_current(
            f"checkout:{customer_id}:{data.request_key}"
        )
        if row is None or row.customer_id != customer_id:
            raise NotFoundException(
                message="Checkout request not found",
                message_code="checkout_not_found",
                entity="checkout",
                identifier="request_key",
                identifier_value=data.request_key,
            )
        return CheckoutRead.model_validate(row, from_attributes=True)
