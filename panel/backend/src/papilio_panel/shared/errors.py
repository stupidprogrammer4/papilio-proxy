"""Application errors independent of HTTP and persistence."""


class ApplicationError(Exception):
    """A caller-safe application failure."""

    code = "operation_failed"


class Conflict(ApplicationError):
    """The operation conflicts with committed state."""

    code = "state_conflict"


class InvalidInput(ApplicationError):
    """The supplied operation input is invalid."""

    code = "invalid_input"


class AuthenticationRejected(ApplicationError):
    """Credentials do not grant access to this interface."""

    code = "invalid_credentials"


class Missing(ApplicationError):
    """A required record is absent from the authorized scope."""

    code = "not_found"
