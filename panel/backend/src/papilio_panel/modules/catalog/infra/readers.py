"""Declared product/offer read shapes with owner and core-parent scopes."""

from uuid import UUID

from django.core.paginator import EmptyPage, Paginator
from django.db.models import F, QuerySet

from papilio_panel.shared.errors import Missing
from papilio_panel.shared.money import Currency

from ..domain import ProductDefinition, ProductOfferRead, ProductPage, ProductRead, ProductSearch
from ..models import Product, ProductOffer


def offer_read(row: ProductOffer) -> ProductOfferRead:
    definition = ProductDefinition(
        row.name,
        row.core_id,
        row.inbound_id,
        row.price_minor,
        Currency(row.currency),
        row.requested_user_level,
        row.is_active,
    )
    return ProductOfferRead(row.id, row.product_id, row.revision, definition, row.user_level)


def product_read(row: Product) -> ProductRead:
    if row.current_offer is None:
        raise Missing("The product offer was not found.")
    return ProductRead(row.id, row.owner_id, offer_read(row.current_offer))


def owned_products(actor_id: int) -> QuerySet[Product]:
    return Product.objects.filter(
        owner_id=actor_id,
        current_offer__product_id=F("id"),
        current_offer__revision=F("revision"),
        current_offer__core__owner_id=actor_id,
        current_offer__core__node__owner_id=actor_id,
        current_offer__inbound__core_id=F("current_offer__core_id"),
    ).select_related("current_offer")


class DjangoProductReader:
    def read(self, product_id: UUID, actor_id: int) -> ProductRead:
        try:
            row = owned_products(actor_id).get(pk=product_id)
        except Product.DoesNotExist as error:
            raise Missing("The product was not found.") from error
        return product_read(row)

    def read_offer(self, offer_id: UUID, actor_id: int) -> ProductOfferRead:
        try:
            row = ProductOffer.objects.get(
                pk=offer_id,
                product__owner_id=actor_id,
                core__owner_id=actor_id,
                core__node__owner_id=actor_id,
                inbound__core_id=F("core_id"),
            )
        except ProductOffer.DoesNotExist as error:
            raise Missing("The product offer was not found.") from error
        return offer_read(row)

    def search(self, values: ProductSearch) -> ProductPage:
        rows = owned_products(values.actor_id).order_by("created_at", "id")
        if values.query:
            rows = rows.filter(current_offer__name__icontains=values.query)
        if values.active_only:
            rows = rows.filter(current_offer__is_active=True)
        paginator = Paginator(rows, values.page_size)
        try:
            page = paginator.page(values.page)
        except EmptyPage as error:
            raise Missing("The product page was not found.") from error
        return ProductPage(
            tuple(product_read(row) for row in page), paginator.count, values.page, values.page_size
        )
