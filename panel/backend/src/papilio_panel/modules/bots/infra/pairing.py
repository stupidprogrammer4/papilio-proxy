"""Create high-entropy expiring pairing capabilities without storing their secret."""

import hashlib
import secrets
from datetime import timedelta

from django.utils import timezone

from ..domain import PairingSecret


class NativePairingIssuer:
    def issue(self, lifetime_seconds: int) -> PairingSecret:
        parameter = "pair_" + secrets.token_urlsafe(24)
        return PairingSecret(
            parameter=parameter,
            digest=hashlib.sha256(parameter.encode()).hexdigest(),
            expires_at=timezone.now() + timedelta(seconds=lifetime_seconds),
        )
