"""Native per-operator Telegram identity uniqueness and protected customer binding."""

from uuid import UUID

from papilio_panel.shared.errors import Conflict

from ..domain import BindingReservation, CustomerBinding
from ..models import ShopCustomer


class DjangoCustomerBindingStorage:
    def reserve(self, owner_id: int, telegram_user_id: int) -> BindingReservation:
        row, created = ShopCustomer.objects.get_or_create(
            owner_id=owner_id, telegram_user_id=telegram_user_id
        )
        return BindingReservation(
            CustomerBinding(row.id, row.owner_id, row.telegram_user_id, row.customer_id), created
        )

    def bind(self, binding_id: UUID, owner_id: int, customer_id: UUID) -> None:
        updated = ShopCustomer.objects.filter(
            pk=binding_id, owner_id=owner_id, customer_id__isnull=True
        ).update(customer_id=customer_id)
        if updated != 1:
            raise Conflict("The Telegram customer binding already belongs to an account.")
