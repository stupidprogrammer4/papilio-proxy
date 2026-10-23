"""Native unique identity and same-row CAS for immutable offer publication."""

from uuid import UUID

from django.db.models import F

from papilio_panel.shared.errors import Conflict

from ..domain import ProductChange, ProductCreate, ProductCreation, ProductDefinition, ProductRead
from ..models import Product, ProductOffer
from .readers import DjangoProductReader, offer_read


def write_offer(
    product_id: UUID, revision: int, definition: ProductDefinition, user_level: int
) -> None:
    offer = ProductOffer.objects.create(
        product_id=product_id,
        revision=revision,
        name=definition.name,
        core_id=definition.core_id,
        inbound_id=definition.inbound_id,
        price_minor=definition.price_minor,
        currency=definition.currency,
        requested_user_level=definition.user_level,
        user_level=user_level,
        is_active=definition.is_active,
    )
    Product.objects.filter(pk=product_id, revision=revision).update(current_offer=offer)


class DjangoProductStorage(DjangoProductReader):
    def create(self, values: ProductCreate, user_level: int) -> ProductCreation:
        row, created = Product.objects.get_or_create(
            owner_id=values.actor_id, request_key=values.request_key
        )
        if created:
            write_offer(row.id, 1, values.definition, user_level)
        original = ProductOffer.objects.get(product_id=row.id, revision=1)
        return ProductCreation(
            self.read(row.id, values.actor_id), offer_read(original).definition, created
        )

    def change(self, values: ProductChange, user_level: int) -> ProductRead:
        changed = Product.objects.filter(
            pk=values.product_id, owner_id=values.actor_id, revision=values.expected_revision
        ).update(revision=F("revision") + 1)
        if changed != 1:
            raise Conflict("The product changed. Refresh its current revision.")
        write_offer(values.product_id, values.expected_revision + 1, values.definition, user_level)
        return self.read(values.product_id, values.actor_id)
