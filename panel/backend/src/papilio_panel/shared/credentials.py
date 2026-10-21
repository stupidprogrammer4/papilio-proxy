"""Native authenticated encryption using the installation's signing-key entropy."""

from base64 import urlsafe_b64encode

from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings
from django.utils.crypto import salted_hmac


def credential_cipher() -> MultiFernet:
    secrets = [settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS]
    keys = [
        urlsafe_b64encode(
            salted_hmac(
                "papilio.credentials.v1",
                "fernet-key",
                secret=secret,
                algorithm="sha256",
            ).digest()
        )
        for secret in secrets
    ]
    return MultiFernet([Fernet(key) for key in keys])
