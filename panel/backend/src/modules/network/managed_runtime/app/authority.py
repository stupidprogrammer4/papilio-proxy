"""Fail-closed prerequisite boundary; not a paid activation implementation."""

from papilio.errors.exceptions import ConflictException

from src.modules.network.managed_runtime.domain.contracts import (
    ManagedRuntimeReadiness,
)


class ManagedRuntimeAuthority:
    def readiness(self) -> ManagedRuntimeReadiness:
        return ManagedRuntimeReadiness()

    def require_paid_activation(self) -> None:
        raise ConflictException(
            unique_dict={},
            message="Managed admission authority is not available.",
            message_code="managed_authority_prerequisites_pending",
        )
