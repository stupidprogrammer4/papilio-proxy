from datetime import UTC

from papilio.infra.db.tools.decorators import transactional

from src.modules.network.core_runtime.app.commands import conflict, now_utc
from src.modules.network.core_runtime.domain.models import (
    CoreRuntimeStateModel,
)
from src.modules.network.core_runtime.domain.results import (
    RuntimeUsageObservationOut,
)
from src.modules.network.core_runtime.domain.usage import (
    RuntimeUsageObservation,
)
from src.modules.network.core_runtime.interfaces import (
    IInstalledProfileQuery,
    IRuntimeRevisionService,
    IRuntimeStateService,
)
from src.modules.network.cores.interfaces import ICoreService
from src.modules.network.nodes.interfaces import INodeService


class CoreUsageObservationCommand:
    def __init__(
        self,
        states: IRuntimeStateService,
        revisions: IRuntimeRevisionService,
        installed: IInstalledProfileQuery,
        cores: ICoreService,
        nodes: INodeService,
    ) -> None:
        self.states, self.revisions, self.installed, self.cores, self.nodes = (
            states,
            revisions,
            installed,
            cores,
            nodes,
        )

    @transactional
    async def observe(
        self, code: str, key: str, core_id: int, data: RuntimeUsageObservation
    ) -> RuntimeUsageObservationOut:
        node = await self.nodes.authenticate(code, key)
        core = await self.cores.get(core_id)
        if core.node_id != node.id:
            raise conflict("runtime_node_mismatch")
        await self.states.lock_core(core_id)
        state = await self.states.current(core_id)
        if (
            state is None
            or state.applied_revision_id != data.runtime_revision_id
            or state.observed_process_epoch != data.process_epoch
        ):
            raise conflict("runtime_usage_observation_invalid")
        revision = await self.revisions.get(data.runtime_revision_id, core_id)
        if (
            revision.usage_sha256 != data.usage_sha256
            or revision.membership_sha256 != data.membership_sha256
        ):
            raise conflict("runtime_usage_observation_invalid")
        if data.observed_status == "running":
            if state.observed_status != "running":
                raise conflict("runtime_usage_observation_stopped")
            if not await self.installed.matches_current(core_id, revision.id):
                raise conflict("runtime_usage_snapshot_stale")
        now = now_utc()
        await self.states.change(
            state,
            CoreRuntimeStateModel.patch(
                observed_status=data.observed_status,
                last_observed_at=now,
            ),
        )
        return RuntimeUsageObservationOut(
            core_id=core_id,
            runtime_revision_id=revision.id,
            observed_status=data.observed_status,
            last_observed_at=now.replace(tzinfo=UTC),
        )
