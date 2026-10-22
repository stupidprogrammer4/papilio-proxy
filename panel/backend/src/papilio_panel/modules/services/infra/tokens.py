"""Use native Django signing for a revocable service-specific subscription grant."""

from uuid import UUID

from django.conf import settings
from django.core import signing

from papilio_panel.shared.errors import Missing

from ..domain import SubscriptionGrant


class NativeSubscriptionTokens:
    def signer(self) -> signing.Signer:
        return signing.Signer(salt=f"{settings.PAPILIO_NAMESPACE}.service-subscription")

    def issue(self, grant: SubscriptionGrant) -> str:
        return self.signer().sign_object(
            {"service_id": str(grant.service_id), "nonce": str(grant.nonce)}
        )

    def verify(self, token: str) -> SubscriptionGrant:
        try:
            payload = self.signer().unsign_object(token)
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("service_id"), str)
                or not isinstance(payload.get("nonce"), str)
            ):
                raise ValueError("Invalid subscription fields.")
            grant = SubscriptionGrant(UUID(payload["service_id"]), UUID(payload["nonce"]))
        except (signing.BadSignature, ValueError, TypeError, KeyError) as error:
            raise Missing("The subscription is unavailable.") from error
        return grant
