import asyncio

from src.config.settings import PapilioSettings
from src.modules.network.core_runtime.app.usage_encoding import (
    RuntimeUsageEncoding,
)
from src.modules.network.core_runtime.domain.usage import (
    CoreUsageCapacity,
    RuntimeUsageCapability,
)
from src.modules.network.core_runtime.infra.usage import (
    RuntimePeerState,
    RuntimeUsageEndpointReader,
)


class CoreUsagePolicyQuery:
    def __init__(
        self, reader: RuntimeUsageEndpointReader, settings: PapilioSettings
    ) -> None:
        self.reader, self.settings = reader, settings

    @staticmethod
    def peer_reason(
        peers: tuple[RuntimePeerState, ...],
        policy: CoreUsageCapacity,
        ports: list[int],
        key: str,
    ) -> str | None:
        for peer in peers:
            if peer.observed_status == "stopped":
                continue
            if (
                peer.observed_status != "running"
                or peer.encrypted_usage is None
            ):
                return "runtime_usage_peer_not_stopped"
            snapshot = RuntimeUsageEncoding.decode(peer.encrypted_usage, key)
            if not RuntimeUsageEncoding.compatible(
                snapshot, peer.core_id, policy, ports
            ):
                return "runtime_usage_peer_guard_stale"
        return None

    async def admission(
        self, core_id: int, node_id: int, kind: str, current: bool = True
    ) -> str | None:
        policy = self.settings.core_usage
        if policy is not None and policy.mode != "disabled":
            grants = await self.reader.core_usage_grants(
                core_id, False, current, policy.max_open_usage_grants + 1
            )
            if len(grants) > policy.max_open_usage_grants:
                return "runtime_usage_grant_capacity"
            if grants:
                return "runtime_usage_unresolved_grants"
        capability = await self.capability(core_id, node_id, kind, current)
        if not capability.protected_ports:
            return None
        if not capability.available:
            return capability.reason_code
        policy = self.settings.core_usage
        assert policy is not None
        rows = await self.reader.endpoints(
            node_id, policy.max_node_endpoints + 1, current
        )
        peers = sorted({row.core_id for row in rows} - {core_id})
        pending = await self.reader.pending_starts(
            peers,
            ["queued", "leased"],
            ["apply", "restart", "rollback"],
            "reconcile",
            "restore",
            current,
            policy.max_node_endpoints + 1,
        )
        if pending:
            return "runtime_usage_peer_start_pending"
        sizes = await self.reader.peer_usage_sizes(
            peers, current, policy.max_node_endpoints + 1
        )
        active = [peer for peer in sizes if peer.observed_status != "stopped"]
        if any(
            peer.observed_status != "running" or peer.usage_bytes is None
            for peer in active
        ):
            return "runtime_usage_peer_not_stopped"
        if (
            sum(peer.usage_bytes or 0 for peer in active)
            > policy.max_peer_usage_bytes
        ):
            return "runtime_usage_peer_payload_capacity"
        states = await self.reader.peer_states(
            [peer.core_id for peer in active],
            current,
            policy.max_node_endpoints + 1,
        )
        reason = await asyncio.to_thread(
            self.peer_reason,
            tuple(states),
            policy,
            capability.protected_ports,
            self.settings.configuration_encryption_key,
        )
        return reason

    async def capability(
        self, core_id: int, node_id: int, kind: str, current: bool = False
    ) -> RuntimeUsageCapability:
        policy = self.settings.core_usage
        if policy is None or policy.mode == "disabled":
            return RuntimeUsageCapability(
                mode="disabled",
                configured_port=None,
                available=False,
                reason_code="runtime_usage_disabled",
                protected_ports=[],
            )
        port = policy.stats_ports.get(core_id)
        rows = await self.reader.endpoints(
            node_id, policy.max_node_endpoints + 1, current
        )
        owners = {row.core_id for row in rows}
        reservations = [
            policy.stats_ports[item]
            for item in owners
            if item in policy.stats_ports
        ]
        protected = sorted(set(reservations))
        reason = None
        if len(rows) > policy.max_node_endpoints:
            reason = "runtime_usage_endpoint_capacity"
        elif len(reservations) != len(protected) or any(
            row.listen_port in reservations for row in rows
        ):
            reason = "runtime_usage_port_conflict"
        elif protected and (kind != "xray" or port is None):
            reason = "runtime_usage_isolation_required"
        elif kind != "xray":
            reason = "runtime_usage_kind_unavailable"
        elif port is None:
            reason = "runtime_usage_port_unconfigured"
        return RuntimeUsageCapability(
            mode=policy.mode,
            configured_port=port,
            available=reason is None,
            reason_code=reason,
            protected_ports=protected,
        )
