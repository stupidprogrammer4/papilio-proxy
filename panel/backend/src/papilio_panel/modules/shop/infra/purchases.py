"""Native immutable purchase confirmations and customer-scoped order linkage."""

from uuid import UUID

from django.db.models import Q

from papilio_panel.shared.errors import Conflict, Missing

from ..domain import PurchaseConfirmation
from ..models import PurchaseIntent


def confirmation_read(row: PurchaseIntent) -> PurchaseConfirmation:
    return PurchaseConfirmation(
        row.id,
        row.bot_id,
        row.customer_id,
        row.product_id,
        row.offer_revision,
        row.service_name,
        row.expires_at,
        row.order_id,
    )


class DjangoPurchaseConfirmationStorage:
    def reserve(self, values: PurchaseConfirmation) -> PurchaseConfirmation:
        row, _ = PurchaseIntent.objects.get_or_create(
            pk=values.id,
            defaults={
                "bot_id": values.bot_id,
                "customer_id": values.customer_id,
                "product_id": values.product_id,
                "offer_revision": values.offer_revision,
                "service_name": values.service_name,
                "expires_at": values.expires_at,
            },
        )
        result = confirmation_read(row)
        if (
            result.bot_id != values.bot_id
            or result.customer_id != values.customer_id
            or result.product_id != values.product_id
            or result.offer_revision != values.offer_revision
            or result.service_name != values.service_name
        ):
            raise Conflict("The confirmation identity already belongs to another offer.")
        return result

    def read(self, confirmation_id: UUID, bot_id: UUID, customer_id: UUID) -> PurchaseConfirmation:
        try:
            row = PurchaseIntent.objects.get(
                pk=confirmation_id, bot_id=bot_id, customer_id=customer_id
            )
        except PurchaseIntent.DoesNotExist as error:
            raise Missing(
                "The purchase confirmation was not found in this customer chat."
            ) from error
        return confirmation_read(row)

    def complete(self, confirmation: PurchaseConfirmation, order_id: UUID) -> None:
        updated = PurchaseIntent.objects.filter(
            Q(order_id__isnull=True) | Q(order_id=order_id),
            pk=confirmation.id,
            bot_id=confirmation.bot_id,
            customer_id=confirmation.customer_id,
        ).update(order_id=order_id)
        if updated != 1:
            raise Conflict("The purchase confirmation already belongs to a different order.")
