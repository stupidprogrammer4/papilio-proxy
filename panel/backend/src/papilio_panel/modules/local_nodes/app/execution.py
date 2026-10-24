"""Coordinate authorized private bootstrap publication and actual node observation."""

from uuid import UUID

from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.modules.nodes.domain import NodeProbe
from papilio_panel.modules.nodes.interfaces import NodeCapability, NodeConnectivityCapability
from papilio_panel.shared.operations import OperationStatus

from ..domain import LocalAttempt, LocalBootstrap, LocalClaim
from ..interfaces import (
    LocalDeliverySchedule,
    LocalFiles,
    LocalNodeCapability,
    LocalWorkStorage,
)


class LocalExecution:
    def __init__(
        self,
        storage: LocalWorkStorage,
        access: AdminAccessCapability,
        management: LocalNodeCapability,
        nodes: NodeCapability,
        connectivity: NodeConnectivityCapability,
        files: LocalFiles,
        schedule: LocalDeliverySchedule,
    ) -> None:
        self.storage, self.access, self.management = storage, access, management
        self.nodes, self.connectivity, self.files, self.schedule = (
            nodes,
            connectivity,
            files,
            schedule,
        )

    def begin(self, operation_id: UUID) -> LocalAttempt:
        if not self.management.defaults().available or not self.schedule.enabled():
            return LocalAttempt()
        work = self.storage.read(operation_id)
        record = work.record
        if (
            record.operation.id != operation_id
            or not record.delivery.enabled
            or work.operation.status not in (OperationStatus.QUEUED, OperationStatus.RUNNING)
        ):
            return LocalAttempt()
        if self.access.owner_permitted(record.owner_id):
            node = self.nodes.read(record.node_id, record.owner_id)
            issue = self.nodes.read_work(record.node_id, record.issue_operation_id, record.owner_id)
            if not node.credentials_ready and issue.status in (
                OperationStatus.QUEUED,
                OperationStatus.RUNNING,
            ):
                return LocalAttempt(retry_after_seconds=record.delivery.retry_interval_seconds)
        return LocalAttempt(claim=self.storage.claim(operation_id))

    def prepare(self, claim: LocalClaim) -> None:
        record = claim.work.record
        if not self.access.owner_permitted(record.owner_id):
            self.reject(claim, "access_revoked")
            return
        if not self.schedule.enabled() or not self.storage.active(claim):
            self.storage.release(claim)
            return
        current = self.management.read(record.owner_id)
        node = self.nodes.read(current.node_id, current.owner_id)
        if not node.credentials_ready:
            self.reject(claim, "credentials_failed")
            return
        bootstrap = self.nodes.bootstrap(node.id, node.owner_id)
        if not self.storage.active(claim):
            self.storage.release(claim)
            return
        self.files.publish(
            LocalBootstrap(claim.work.operation.id, node, current.definition, bootstrap)
        )
        if not self.storage.active(claim):
            self.storage.release(claim)
            return
        observed = self.connectivity.probe(NodeProbe(node.owner_id, node.id))
        self.storage.finish(
            claim,
            None if observed.reachable else observed.error_code or "node_unreachable",
            retryable=not observed.reachable,
        )

    def reject(self, claim: LocalClaim, error_code: str, *, retryable: bool = False) -> None:
        self.storage.finish(claim, error_code, retryable=retryable)
