"""Native owner/request uniqueness and transaction-finalized order effects."""

from uuid import UUID

from papilio_panel.shared.errors import Conflict

from ..domain import OrderCreation, OrderRead, OrderState, PurchaseInput, PurchaseTerms
from ..models import Order
from .readers import DjangoOrderReader, order_read


class DjangoOrderStorage(DjangoOrderReader):
    def reserve(self, values: PurchaseInput, terms: PurchaseTerms) -> OrderCreation:
        row, created = Order.objects.get_or_create(
            owner_id=values.actor_id,
            request_key=values.request_key,
            defaults={
                "customer_id": values.definition.customer_id,
                "product_id": terms.product_id,
                "offer_id": terms.offer_id,
                "offer_revision": terms.offer_revision,
                "product_name": terms.product_name,
                "price_minor": terms.price_minor,
                "currency": terms.currency,
                "core_id": terms.core_id,
                "inbound_id": terms.inbound_id,
                "user_level": terms.user_level,
                "service_name": values.definition.service_name,
            },
        )
        return OrderCreation(order_read(row), created)

    def complete_purchase(
        self, order_id: UUID, actor_id: int, service_id: UUID, wallet_entry_id: UUID | None
    ) -> OrderRead:
        changed = Order.objects.filter(
            pk=order_id, owner_id=actor_id, status=OrderState.PENDING
        ).update(
            status=OrderState.PURCHASED, service_id=service_id, wallet_entry_id=wallet_entry_id
        )
        result = self.read(order_id, actor_id)
        if changed == 0 and (
            result.service_id != service_id or result.wallet_entry_id != wallet_entry_id
        ):
            raise Conflict("The order already has different recorded effects.")
        return result
