"""Native immutable invoice-to-conversation origin, scoped through its invoice."""

from uuid import UUID

from papilio_panel.shared.errors import Conflict

from ..domain import InvoiceOrigin
from ..models import InvoiceConversation


class DjangoInvoiceOriginStorage:
    def create(self, values: InvoiceOrigin) -> None:
        row, _ = InvoiceConversation.objects.get_or_create(
            invoice_id=values.invoice_id, defaults={"event_id": values.event_id}
        )
        if row.event_id != values.event_id:
            raise Conflict("This invoice already belongs to its original conversation.")

    def find(self, invoice_id: UUID, actor_id: int) -> InvoiceOrigin | None:
        row = (
            InvoiceConversation.objects.select_related("invoice", "event__bot")
            .filter(invoice_id=invoice_id, invoice__owner_id=actor_id)
            .first()
        )
        return (
            InvoiceOrigin(
                row.invoice_id,
                row.event_id,
                row.event.bot_id,
                row.invoice.owner_id,
                row.invoice.customer_id,
            )
            if row is not None
            else None
        )
