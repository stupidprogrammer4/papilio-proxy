"""Declared order read facts from owned accepted-term records."""

from uuid import UUID

from django.core.paginator import EmptyPage, Paginator
from django.db.models import F, Q, QuerySet

from papilio_panel.shared.errors import Missing
from papilio_panel.shared.money import Currency

from ..domain import OrderPage, OrderRead, OrderSearch, OrderState, PurchaseTerms
from ..models import Order


def order_read(row: Order) -> OrderRead:
    terms = PurchaseTerms(
        row.product_id,
        row.offer_id,
        row.offer_revision,
        row.product_name,
        row.price_minor,
        Currency(row.currency),
        row.core_id,
        row.inbound_id,
        row.user_level,
    )
    return OrderRead(
        row.id,
        row.owner_id,
        row.customer_id,
        terms,
        row.service_name,
        OrderState(row.status),
        row.service_id,
        row.wallet_entry_id,
        row.created_at,
    )


def owned_orders(actor_id: int) -> QuerySet[Order]:
    return Order.objects.filter(
        owner_id=actor_id,
        customer__owner_id=actor_id,
        product__owner_id=actor_id,
        offer__product_id=F("product_id"),
        core__owner_id=actor_id,
        core__node__owner_id=actor_id,
        inbound__core_id=F("core_id"),
    ).filter(
        Q(service_id__isnull=True)
        | Q(
            service__owner_id=actor_id,
            service__core_id=F("core_id"),
            service__xray__inbound_id=F("inbound_id"),
        ),
        Q(wallet_entry_id__isnull=True)
        | Q(wallet_entry__wallet__customer_id=F("customer_id"), wallet_entry__actor_id=actor_id),
    )


class DjangoOrderReader:
    def find_request(self, actor_id: int, request_key: UUID) -> OrderRead | None:
        row = owned_orders(actor_id).filter(request_key=request_key).first()
        return order_read(row) if row is not None else None

    def read(self, order_id: UUID, actor_id: int) -> OrderRead:
        try:
            row = owned_orders(actor_id).get(pk=order_id)
        except Order.DoesNotExist as error:
            raise Missing("The order was not found.") from error
        return order_read(row)

    def search(self, values: OrderSearch) -> OrderPage:
        rows = owned_orders(values.actor_id).order_by("created_at", "id")
        if values.customer_id is not None:
            rows = rows.filter(customer_id=values.customer_id)
        if values.query:
            rows = rows.filter(service_name__icontains=values.query)
        paginator = Paginator(rows, values.page_size)
        try:
            page = paginator.page(values.page)
        except EmptyPage as error:
            raise Missing("The order page was not found.") from error
        return OrderPage(
            tuple(order_read(row) for row in page), paginator.count, values.page, values.page_size
        )
