"""Combine the approved first owner and optional local runtime registration."""

from uuid import uuid4

from django.db import transaction

from papilio_panel.modules.identity.domain import OwnerIdentity
from papilio_panel.modules.identity.interfaces import OwnerSetupCapability

from ..domain import LocalChoice, LocalCreate, OwnerInitialization
from ..interfaces import LocalNodeCapability, LocalRegistrationCapability


class LocalOwnerInitialization:
    def __init__(
        self,
        owners: OwnerSetupCapability,
        management: LocalNodeCapability,
        registration: LocalRegistrationCapability,
    ) -> None:
        self.owners, self.management, self.registration = owners, management, registration

    @transaction.atomic
    def complete(self, values: OwnerInitialization) -> OwnerIdentity:
        defaults = self.management.defaults()
        choice = values.local_node or LocalChoice(enabled=defaults.available)
        owner = self.owners.complete(values.owner)
        if choice.enabled:
            self.registration.create(
                LocalCreate(
                    owner.id,
                    uuid4(),
                    choice.definition or defaults.definition,
                    choice.delivery,
                )
            )
        return owner
