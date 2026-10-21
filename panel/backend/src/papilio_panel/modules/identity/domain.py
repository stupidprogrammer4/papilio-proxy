"""Typed identity inputs and read results."""

from dataclasses import dataclass


@dataclass(frozen=True)
class OwnerSetupInput:
    token: str
    username: str
    password: str


@dataclass(frozen=True)
class OwnerIdentity:
    id: int
    username: str


@dataclass(frozen=True)
class AdminPrincipal:
    id: int
    username: str
    is_active: bool
    is_staff: bool
    is_superuser: bool = False


@dataclass(frozen=True)
class AdminSession:
    username: str
    scopes: tuple[str, ...]
    csrf_token: str
