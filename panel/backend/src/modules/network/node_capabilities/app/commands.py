import asyncio
from datetime import UTC, datetime, timedelta

from papilio.errors.exceptions import ConflictException
from papilio.infra.db.transaction import active_transaction
from papilio.infra.db.uow import MySQLUnitOfWork

from src.modules.network.node_capabilities.app.encoding import (
    NodeCapabilityEncoding,
)
from src.modules.network.node_capabilities.app.observations import (
    NodeCapabilityPresentation,
)
from src.modules.network.node_capabilities.domain.contracts import (
    NodeCapabilityCapacity,
    NodeCapabilityReceived,
)
from src.modules.network.node_capabilities.domain.models import (
    NodeCapabilityObservationModel,
)
from src.modules.network.node_capabilities.domain.results import (
    NodeCapabilityReceipt,
)
from src.modules.network.node_capabilities.infra.readers import (
    NodeCapabilityObservationReader,
)
from src.modules.network.node_capabilities.interfaces import (
    INodeCapabilityService,
)
from src.modules.network.nodes.interfaces import INodeService


def capability_conflict(code: str) -> ConflictException:
    return ConflictException(
        message="Capability observation cannot be accepted.",
        message_code=code,
        unique_dict={},
    )


class NodeCapabilityCommand:
    def __init__(
        self,
        nodes: INodeService,
        observations: INodeCapabilityService,
        reader: NodeCapabilityObservationReader,
        capacity: NodeCapabilityCapacity,
        uow: MySQLUnitOfWork,
    ) -> None:
        self.uow = uow
        self.nodes, self.observations, self.reader, self.capacity = (
            nodes,
            observations,
            reader,
            capacity,
        )

    async def receive(
        self, code: str, agent_key: str, data: NodeCapabilityReceived
    ) -> NodeCapabilityReceipt:
        # Metadata admission owns a standalone operation. Existing SQL work
        # must not be committed, rolled back or have its isolation changed.
        if active_transaction() is not None or self.uow.in_transaction:
            raise capability_conflict(
                "capability_standalone_operation_required"
            )
        await self.uow.session.connection(
            execution_options={"isolation_level": "READ COMMITTED"}
        )
        async with self.uow.transaction():
            result = await self._receive(code, agent_key, data)
            return result

    async def _receive(
        self, code: str, agent_key: str, data: NodeCapabilityReceived
    ) -> NodeCapabilityReceipt:
        node = await self.nodes.authenticate(code, agent_key)
        await self.nodes.locked(node.id)
        node = await self.nodes.authenticate(code, agent_key)
        encoded = await asyncio.to_thread(
            NodeCapabilityEncoding.encode, data.report
        )
        if encoded.sha256 != data.report_sha256:
            raise capability_conflict("capability_report_digest_invalid")
        existing = await self.observations.find(node.id, data.report_id)
        if existing is not None:
            if existing.report_sha256 != encoded.sha256:
                raise capability_conflict("capability_report_reused")
            return NodeCapabilityPresentation.receipt(existing, node.code)
        policy = self.capacity
        if not policy.enabled:
            raise capability_conflict("capability_observations_disabled")
        if encoded.byte_count > policy.max_report_bytes:
            raise capability_conflict("capability_report_capacity")
        now = datetime.now(UTC)
        if data.report.observed_at > now + timedelta(
            seconds=policy.future_skew_seconds
        ):
            raise capability_conflict("capability_report_future")
        if data.report.observed_at < now - timedelta(
            seconds=policy.max_report_age_seconds
        ):
            raise capability_conflict("capability_report_expired")
        count = await self.reader.count(node.id)
        if count >= policy.max_history_per_node:
            raise capability_conflict("capability_history_capacity")
        row = await self.observations.create(
            NodeCapabilityObservationModel(
                node_id=node.id,
                report_id=data.report_id,
                report_sha256=encoded.sha256,
                normalized_report=encoded.source,
                observed_at=data.report.observed_at.replace(tzinfo=None),
                received_at=now.replace(tzinfo=None),
            )
        )
        return NodeCapabilityPresentation.receipt(row, node.code)
