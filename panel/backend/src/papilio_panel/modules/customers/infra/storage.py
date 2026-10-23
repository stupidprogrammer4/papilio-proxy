"""Scoped native customer reads and idempotent registration."""

from uuid import UUID

from django.core.paginator import EmptyPage, Paginator

from papilio_panel.shared.errors import Missing

from ..domain import CustomerCreate, CustomerCreation, CustomerPage, CustomerRead, CustomerSearch
from ..models import CustomerAccount


def customer_read(row: CustomerAccount) -> CustomerRead:
    return CustomerRead(row.id, row.owner_id, row.name)


class DjangoCustomerStorage:
    def create(self, values: CustomerCreate) -> CustomerCreation:
        row, created = CustomerAccount.objects.get_or_create(
            owner_id=values.actor_id,
            request_key=values.request_key,
            defaults={"name": values.name},
        )
        return CustomerCreation(customer_read(row), created)

    def read(self, customer_id: UUID, actor_id: int) -> CustomerRead:
        try:
            row = CustomerAccount.objects.get(pk=customer_id, owner_id=actor_id)
        except CustomerAccount.DoesNotExist as error:
            raise Missing("The customer account was not found.") from error
        return customer_read(row)

    def search(self, values: CustomerSearch) -> CustomerPage:
        rows = CustomerAccount.objects.filter(owner_id=values.actor_id).order_by("created_at", "id")
        if values.query:
            rows = rows.filter(name__icontains=values.query)
        paginator = Paginator(rows, values.page_size)
        try:
            page = paginator.page(values.page)
        except EmptyPage as error:
            raise Missing("The customer page was not found.") from error
        return CustomerPage(
            tuple(customer_read(row) for row in page),
            paginator.count,
            values.page,
            values.page_size,
        )
