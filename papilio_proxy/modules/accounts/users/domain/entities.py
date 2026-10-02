from dataclasses import dataclass


class UserBlockedError(PermissionError):
    """An administrator has disabled all service access for this user."""


class UnknownUserError(LookupError):
    """The selected Telegram user does not exist."""


@dataclass(frozen=True, slots=True)
class UserAccessResult:
    telegram_id: int
    is_blocked: bool
    reason: str
    enforcement_pending: bool = False
