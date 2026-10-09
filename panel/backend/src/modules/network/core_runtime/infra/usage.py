from dataclasses import dataclass

from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import func, or_, select
from sqlmodel import col

from src.modules.network.configurations.infra.tables import (
    ConfigurationTable,
    ProfileTable,
)
from src.modules.network.core_runtime.infra.tables import (
    CoreRuntimeCommandTable,
    CoreRuntimeRevisionTable,
    CoreRuntimeStateTable,
)
from src.modules.network.cores.infra.tables import CoreTable
from src.modules.network.usage.infra.tables import UsageGrantTable


@dataclass(frozen=True, slots=True)
class NodeRuntimeEndpoint:
    core_id: int
    listen_port: int | None


@dataclass(frozen=True, slots=True)
class RuntimePeerState:
    core_id: int
    observed_status: str | None
    encrypted_usage: str | None


@dataclass(frozen=True, slots=True)
class RuntimePeerUsageSize:
    core_id: int
    observed_status: str | None
    usage_bytes: int | None


@dataclass(frozen=True, slots=True)
class CoreOpenUsageGrant:
    grant_id: int
    profile_id: int
    subscription_id: int
    generation: int
    process_epoch: str | None


class RuntimeUsageEndpointReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def core_usage_grants(
        self, core_id: int, closed: bool, current: bool, limit: int
    ) -> list[CoreOpenUsageGrant]:
        query = (
            select(
                col(UsageGrantTable.id),
                col(UsageGrantTable.profile_id),
                col(UsageGrantTable.subscription_id),
                col(UsageGrantTable.generation),
                col(UsageGrantTable.process_epoch),
            )
            .join(
                ProfileTable,
                col(ProfileTable.id) == col(UsageGrantTable.profile_id),
            )
            .join(
                ConfigurationTable,
                col(ConfigurationTable.id)
                == col(ProfileTable.configuration_id),
            )
            .where(
                col(ConfigurationTable.core_id) == core_id,
                col(UsageGrantTable.is_closed).is_(closed),
            )
            .order_by(col(UsageGrantTable.id))
            .limit(limit)
        )
        if current:
            query = query.with_for_update(read=True)
        result = await self.uow.execute(query)
        return [CoreOpenUsageGrant(*row) for row in result]

    async def endpoints(
        self, node_id: int, limit: int, current: bool
    ) -> list[NodeRuntimeEndpoint]:
        # Core node ownership is immutable through the public application.
        # Do not lock peer core lifecycle rows while holding the owning core.
        ownership = (
            select(col(CoreTable.id))
            .where(col(CoreTable.node_id) == node_id)
            .order_by(col(CoreTable.id))
            .limit(limit)
        )
        if current:
            ownership = ownership.with_for_update(read=True)
        cores = await self.uow.execute(ownership)
        core_ids = list(cores.scalars())
        query = (
            select(
                col(ConfigurationTable.core_id),
                col(ConfigurationTable.listen_port),
            )
            .where(col(ConfigurationTable.core_id).in_(core_ids))
            .order_by(
                col(ConfigurationTable.core_id), col(ConfigurationTable.id)
            )
            .limit(limit)
        )
        if current:
            query = query.with_for_update(read=True)
        result = await self.uow.execute(query)
        rows = [NodeRuntimeEndpoint(row[0], row[1]) for row in result]
        configured = {row.core_id for row in rows}
        return rows + [
            NodeRuntimeEndpoint(core, None)
            for core in core_ids
            if core not in configured
        ]

    async def peer_usage_sizes(
        self, core_ids: list[int], current: bool, limit: int
    ) -> list[RuntimePeerUsageSize]:
        query = (
            select(
                col(CoreTable.id),
                col(CoreRuntimeStateTable.observed_status),
                func.octet_length(
                    col(CoreRuntimeRevisionTable.encrypted_usage)
                ),
            )
            .select_from(CoreTable)
            .outerjoin(
                CoreRuntimeStateTable,
                col(CoreRuntimeStateTable.core_id) == col(CoreTable.id),
            )
            .outerjoin(
                CoreRuntimeRevisionTable,
                col(CoreRuntimeStateTable.applied_revision_id)
                == col(CoreRuntimeRevisionTable.id),
            )
            .where(col(CoreTable.id).in_(core_ids))
            .order_by(col(CoreTable.id))
            .limit(limit)
        )
        if current:
            query = query.with_for_update(read=True)
        result = await self.uow.execute(query)
        return [RuntimePeerUsageSize(row[0], row[1], row[2]) for row in result]

    async def peer_states(
        self, core_ids: list[int], current: bool, limit: int
    ) -> list[RuntimePeerState]:
        query = (
            select(
                col(CoreTable.id),
                col(CoreRuntimeStateTable.observed_status),
                col(CoreRuntimeRevisionTable.encrypted_usage),
            )
            .select_from(CoreTable)
            .outerjoin(
                CoreRuntimeStateTable,
                col(CoreRuntimeStateTable.core_id) == col(CoreTable.id),
            )
            .outerjoin(
                CoreRuntimeRevisionTable,
                col(CoreRuntimeStateTable.applied_revision_id)
                == col(CoreRuntimeRevisionTable.id),
            )
            .where(col(CoreTable.id).in_(core_ids))
            .order_by(col(CoreTable.id))
            .limit(limit)
        )
        if current:
            query = query.with_for_update(read=True)
        result = await self.uow.execute(query)
        return [RuntimePeerState(*row) for row in result]

    async def pending_starts(
        self,
        core_ids: list[int],
        states: list[str],
        actions: list[str],
        restore_action: str,
        restore_mode: str,
        current: bool,
        limit: int,
    ) -> list[int]:
        query = (
            select(col(CoreRuntimeCommandTable.core_id))
            .where(
                col(CoreRuntimeCommandTable.core_id).in_(core_ids),
                col(CoreRuntimeCommandTable.state).in_(states),
                or_(
                    col(CoreRuntimeCommandTable.action).in_(actions),
                    (col(CoreRuntimeCommandTable.action) == restore_action)
                    & (
                        col(CoreRuntimeCommandTable.reconcile_mode)
                        == restore_mode
                    ),
                ),
            )
            .order_by(col(CoreRuntimeCommandTable.id))
            .limit(limit)
        )
        if current:
            query = query.with_for_update(read=True)
        result = await self.uow.execute(query)
        return list(result.scalars())
