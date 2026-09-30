from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KpayCredentials:
    username: str
    password: str


class CredentialStorageError(RuntimeError):
    """Encrypted credential storage cannot be read or written safely."""
