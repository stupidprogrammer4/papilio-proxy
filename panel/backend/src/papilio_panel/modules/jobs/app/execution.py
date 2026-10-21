"""Execute a leased diagnostic and commit only the matching claim."""

import math
from uuid import UUID

from django.utils import timezone

from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.shared.operations import OperationStatus

from ..domain import ExecutionOutcome, ProbeKind
from ..interfaces import OperationStorage, ProbeChecks


class ProbeExecution:
    def __init__(
        self, storage: OperationStorage, checks: ProbeChecks, access: AdminAccessCapability
    ) -> None:
        self.storage = storage
        self.checks = checks
        self.access = access

    def execute(self, operation_id: UUID, kind: ProbeKind) -> ExecutionOutcome:
        claim = self.storage.claim(operation_id, kind)
        if claim.operation.kind != kind:
            return ExecutionOutcome()
        if claim.token is None:
            remaining = None
            if claim.operation.status == OperationStatus.RUNNING and claim.operation.lease_until:
                remaining = max(
                    1, math.ceil((claim.operation.lease_until - timezone.now()).total_seconds())
                )
            return ExecutionOutcome(retry_after_seconds=remaining)
        if not self.access.permitted(claim.actor_id):
            self.storage.reject(operation_id, claim.token, "access_revoked")
            return ExecutionOutcome()
        result = self.checks.io() if claim.operation.kind == ProbeKind.IO else self.checks.cpu()
        self.storage.finish(operation_id, claim.token, result)
        return ExecutionOutcome()
