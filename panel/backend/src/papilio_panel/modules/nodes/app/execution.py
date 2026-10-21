"""Revalidate authorization before CPU issuance or external node communication."""

import math
from uuid import UUID

from django.utils import timezone

from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.shared.operations import OperationStatus

from ..domain import CertificateInput, NodeConnection, NodeWorkKind, WorkClaim, WorkOutcome
from ..interfaces import AgentGateway, CertificateIssuer, NodeStorage
from .validation import endpoint_hostname


def waiting_outcome(claim: WorkClaim) -> WorkOutcome:
    remaining = None
    if claim.operation.status == OperationStatus.RUNNING and claim.operation.lease_until:
        remaining = max(
            1, math.ceil((claim.operation.lease_until - timezone.now()).total_seconds())
        )
    return WorkOutcome(retry_after_seconds=remaining)


class NodeExecution:
    def __init__(
        self,
        storage: NodeStorage,
        access: AdminAccessCapability,
        issuer: CertificateIssuer,
        gateway: AgentGateway,
    ) -> None:
        self.storage = storage
        self.access = access
        self.issuer = issuer
        self.gateway = gateway

    def permitted(self, claim: WorkClaim) -> bool:
        return claim.operation.actor_id == claim.node.owner_id and self.access.owner_permitted(
            claim.operation.actor_id
        )

    def issue(self, operation_id: UUID) -> WorkOutcome:
        claim = self.storage.claim(operation_id, NodeWorkKind.ISSUE)
        if claim.operation.kind != NodeWorkKind.ISSUE:
            return WorkOutcome()
        if claim.token is None:
            return waiting_outcome(claim)
        if not self.permitted(claim):
            self.storage.reject(operation_id, claim.token, "access_revoked")
            return WorkOutcome()
        credentials = self.issuer.issue(
            CertificateInput(
                node_id=claim.node.id,
                deployment_id=claim.node.deployment_id,
                hostname=endpoint_hostname(claim.node.endpoint_url),
                policy=claim.node.certificate_policy,
            )
        )
        self.storage.finish_issue(claim, credentials)
        return WorkOutcome()

    def check(self, operation_id: UUID) -> WorkOutcome:
        claim = self.storage.claim(operation_id, NodeWorkKind.CHECK)
        if claim.operation.kind != NodeWorkKind.CHECK:
            return WorkOutcome()
        if claim.token is None:
            return waiting_outcome(claim)
        if not self.permitted(claim):
            self.storage.reject(operation_id, claim.token, "access_revoked")
            return WorkOutcome()
        if not claim.node.credentials_ready:
            self.storage.reject(operation_id, claim.token, "credentials_pending")
            return WorkOutcome()
        credentials = self.storage.credentials(claim.node.id, claim.operation.actor_id)
        result = self.gateway.check(
            NodeConnection(
                node_id=claim.node.id,
                deployment_id=claim.node.deployment_id,
                endpoint_url=claim.node.endpoint_url,
                runtime=claim.node.runtime,
                credentials=credentials,
            )
        )
        self.storage.finish_check(claim, result)
        return WorkOutcome()
