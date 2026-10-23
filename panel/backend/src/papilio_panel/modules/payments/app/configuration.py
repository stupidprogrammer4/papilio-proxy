"""Owner-controlled payment settings without restart or default reapplication."""

from django.db import transaction

from papilio_panel.modules.identity.interfaces import AdminAccessCapability

from ..domain import (
    PaymentDefinition,
    PaymentSettingsChange,
    PaymentSettingsCreate,
    PaymentSettingsRead,
)
from ..interfaces import PaymentSettingsStorage
from .validation import payment_definition, revision


class PaymentConfiguration:
    def __init__(self, storage: PaymentSettingsStorage, access: AdminAccessCapability) -> None:
        self.storage = storage
        self.access = access

    def defaults(self, actor_id: int) -> PaymentDefinition:
        self.access.authorize_owner(actor_id)
        return PaymentDefinition(recipient="", destination="")

    def read(self, actor_id: int) -> PaymentSettingsRead:
        self.access.authorize_owner(actor_id)
        result = self.storage.read(actor_id)
        return result

    @transaction.atomic
    def create(self, values: PaymentSettingsCreate) -> PaymentSettingsRead:
        self.access.authorize_owner(values.actor_id)
        payment_definition(values.definition)
        result = self.storage.create(values)
        return result

    @transaction.atomic
    def change(self, values: PaymentSettingsChange) -> PaymentSettingsRead:
        self.read(values.actor_id)
        payment_definition(values.definition)
        revision(values.expected_revision)
        result = self.storage.change(values)
        return result
