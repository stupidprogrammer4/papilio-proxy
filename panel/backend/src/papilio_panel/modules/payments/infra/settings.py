"""Native singleton payment configuration and same-row revision writes."""

from django.db.models import F

from papilio_panel.shared.errors import Conflict, Missing

from ..domain import PaymentSettingsChange, PaymentSettingsCreate, PaymentSettingsRead
from ..models import PaymentSettings
from .readers import settings_read


class DjangoPaymentSettingsStorage:
    def read(self, actor_id: int) -> PaymentSettingsRead:
        try:
            row = PaymentSettings.objects.get(owner_id=actor_id)
        except PaymentSettings.DoesNotExist as error:
            raise Missing("Configure a payment destination before issuing invoices.") from error
        return settings_read(row)

    def create(self, values: PaymentSettingsCreate) -> PaymentSettingsRead:
        definition = values.definition
        row, _ = PaymentSettings.objects.get_or_create(
            owner_id=values.actor_id,
            defaults={
                "recipient": definition.recipient,
                "destination": definition.destination,
                "instructions": definition.instructions,
                "enabled": definition.enabled,
                "receipt_max_bytes": definition.receipt_max_bytes,
            },
        )
        result = settings_read(row)
        if result.definition != definition:
            raise Conflict(
                "Payment settings already exist. Read and update their current revision."
            )
        return result

    def change(self, values: PaymentSettingsChange) -> PaymentSettingsRead:
        definition = values.definition
        updated = PaymentSettings.objects.filter(
            owner_id=values.actor_id, revision=values.expected_revision
        ).update(
            recipient=definition.recipient,
            destination=definition.destination,
            instructions=definition.instructions,
            enabled=definition.enabled,
            receipt_max_bytes=definition.receipt_max_bytes,
            revision=F("revision") + 1,
        )
        if updated != 1:
            raise Conflict("Payment settings changed. Read their current revision before saving.")
        return self.read(values.actor_id)
