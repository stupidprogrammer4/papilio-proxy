"""Initialize an installation owner using native transaction ownership."""

from django.db import transaction

from papilio_panel.shared.errors import Conflict

from ..domain import OwnerIdentity, OwnerSetupInput
from ..interfaces import CredentialValidation, SetupStorage


class OwnerSetup:
    """Coordinate the single-use grant and first account atomically."""

    def __init__(self, storage: SetupStorage, credentials: CredentialValidation) -> None:
        self.storage = storage
        self.credentials = credentials

    def issue_token(self) -> str:
        if self.storage.is_configured():
            raise Conflict("The installation owner has already been configured.")
        token = self.storage.issue_grant()
        return token

    @transaction.atomic
    def complete(self, values: OwnerSetupInput) -> OwnerIdentity:
        if self.storage.is_configured() or not self.storage.claim_initialization():
            raise Conflict("The installation owner has already been configured.")
        self.storage.consume_grant(values.token)
        self.credentials.validate(values.username, values.password)
        owner = self.storage.create_owner(values.username, values.password)
        self.storage.finish_initialization(owner)
        return owner
