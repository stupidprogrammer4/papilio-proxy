import asyncio
from datetime import UTC

from papilio.errors.exceptions import (
    ConflictException,
    NotFoundException,
    UnAuthorizedException,
)
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import hash_sha256, secure_compare

from src.modules.network.nodes.domain.dtos import ProbeReceived
from src.modules.network.nodes.domain.models import ProbeModel
from src.modules.network.nodes.infra.mysql import (
    NodeRepository,
    ProbeRepository,
)


class ProbeCommand:
    def __init__(self, nodes: NodeRepository, probes: ProbeRepository) -> None:
        self.nodes = nodes
        self.probes = probes

    @handle_conflicts
    @transactional
    async def receive(
        self, code: str, agent_key: str, data: ProbeReceived
    ) -> ProbeModel:
        node = await self.nodes.by_code(code)
        if node is None:
            raise NotFoundException(
                message="نود پیدا نشد.",
                message_code="node_not_found",
                entity="node",
                identifier="code",
                identifier_value=code,
            )
        digest = await asyncio.to_thread(hash_sha256, agent_key)
        if not agent_key or not secure_compare(digest, node.agent_key_hash):
            raise UnAuthorizedException(
                message="دسترسی نود معتبر نیست.",
                message_code="node_unauthorized",
            )
        existing = await self.probes.by_event_id(data.event_id)
        sampled_at = data.sampled_at.astimezone(UTC).replace(
            tzinfo=None, microsecond=0
        )
        if existing is not None:
            if (
                existing.node_id != node.id
                or existing.client_network != data.client_network
                or existing.success != data.success
                or existing.latency_ms != data.latency_ms
                or existing.sampled_at != sampled_at
            ):
                raise ConflictException(
                    message="شناسهٔ سنجش برای گزارش دیگری ثبت شده است.",
                    message_code="probe_event_reused",
                    unique_dict={"event_id": data.event_id},
                )
            return existing
        observed = await self.probes.create(
            ProbeModel(
                event_id=data.event_id,
                node_id=node.id,
                client_network=data.client_network,
                latency_ms=data.latency_ms,
                success=data.success,
                sampled_at=sampled_at,
            )
        )
        return observed
