"""Native Django setup storage and signed-token adaptation."""

from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.contrib.auth.models import User
from django.core import signing
from django.db import IntegrityError
from django.utils import timezone

from papilio_panel.shared.errors import Conflict, InvalidInput

from ..domain import OwnerIdentity
from ..models import OwnerSetupState, SetupGrant

TOKEN_SALT = "papilio.identity.owner-setup.v1"


class DjangoSetupStorage:
    """Persist initialization facts; the application chooses their meaning."""

    def is_configured(self) -> bool:
        initialized = OwnerSetupState.objects.filter(claimed=True).exists()
        native_owner_exists = User.objects.filter(is_superuser=True).exists()
        return initialized or native_owner_exists

    def issue_grant(self) -> str:
        OwnerSetupState.objects.get_or_create(pk=1)
        grant = SetupGrant.objects.create(
            expires_at=timezone.now() + timedelta(seconds=settings.PAPILIO_SETUP_TOKEN_TTL_SECONDS)
        )
        token = signing.dumps({"grant": str(grant.id)}, salt=TOKEN_SALT)
        return token

    def claim_initialization(self) -> bool:
        claimed = OwnerSetupState.objects.filter(pk=1, claimed=False).update(claimed=True)
        return claimed == 1

    def consume_grant(self, token: str) -> None:
        try:
            payload = signing.loads(token, salt=TOKEN_SALT)
            grant_id = UUID(payload["grant"])
        except (signing.BadSignature, ValueError, KeyError, TypeError) as error:
            raise InvalidInput("The setup token is invalid or expired.") from error
        now = timezone.now()
        consumed = SetupGrant.objects.filter(
            pk=grant_id, consumed_at__isnull=True, expires_at__gt=now
        ).update(consumed_at=now)
        if consumed != 1:
            raise InvalidInput("The setup token is invalid or expired.")

    def create_owner(self, username: str, password: str) -> OwnerIdentity:
        try:
            owner = User.objects.create_superuser(username=username, password=password)
        except IntegrityError as error:
            raise Conflict("The account could not be created with these details.") from error
        return OwnerIdentity(id=owner.pk, username=owner.username)

    def finish_initialization(self, owner: OwnerIdentity) -> None:
        OwnerSetupState.objects.filter(pk=1).update(owner_id=owner.id)
