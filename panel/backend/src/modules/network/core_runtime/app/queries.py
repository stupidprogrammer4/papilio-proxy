from datetime import UTC, datetime

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.network.core_runtime.domain.dtos import (
    RuntimeAction,
    RuntimeSearch,
)
from src.modules.network.core_runtime.domain.models import (
    CoreRuntimeCommandModel,
)
from src.modules.network.core_runtime.domain.results import (
    RuntimeRevisionOut,
    RuntimeStateOut,
)
from src.modules.network.core_runtime.infra.metadata import (
    RuntimeRevisionMetadataReader,
)
from src.modules.network.core_runtime.infra.readers import (
    RuntimeSnapshotReader,
)
from src.modules.network.core_runtime.interfaces import (
    ICoreUsagePolicyQuery,
    IRuntimeCommandService,
    IRuntimeStateService,
)
from src.modules.network.cores.interfaces import ICoreService
from src.modules.network.nodes.interfaces import INodeService


class CoreRuntimeQuery:
    def __init__(
        self,
        states: IRuntimeStateService,
        commands: IRuntimeCommandService,
        cores: ICoreService,
        nodes: INodeService,
        reader: RuntimeSnapshotReader,
        metadata: RuntimeRevisionMetadataReader,
        settings: PapilioSettings,
        usage: ICoreUsagePolicyQuery,
    ) -> None:
        self.states, self.command_service = states, commands
        self.metadata = metadata
        self.usage = usage
        self.cores, self.nodes, self.reader, self.settings = (
            cores,
            nodes,
            reader,
            settings,
        )

    async def state(self, core_id: int) -> RuntimeStateOut:
        core = await self.cores.get(core_id)
        usage = await self.usage.capability(core.id, core.node_id, core.kind)
        row = await self.states.find(core_id)
        policy = self.settings.core_runtime
        enabled = policy is not None and policy.enabled
        allow_start = enabled and policy is not None and policy.allow_start
        actions: list[RuntimeAction] = (
            ["validate", "stop", "reconcile"] if enabled else []
        )
        start_blocked_reason = None
        if allow_start:
            start_blocked_reason = await self.usage.admission(
                core.id, core.node_id, core.kind, current=False
            )
            if start_blocked_reason is None:
                actions.extend(["apply", "restart", "rollback"])
        if row is None:
            return RuntimeStateOut(
                id=None,
                core_id=core_id,
                revision=1,
                desired_revision_id=None,
                applied_revision_id=None,
                validated_revision_id=None,
                observed_status="unknown",
                automation_paused=False,
                last_observed_at=None,
                enabled=enabled,
                allow_start=allow_start,
                start_blocked_reason=start_blocked_reason,
                allowed_actions=actions,
                usage=usage,
            )
        return RuntimeStateOut(
            **row.model_dump(),
            enabled=enabled,
            allow_start=allow_start,
            start_blocked_reason=start_blocked_reason,
            allowed_actions=actions,
            usage=usage,
        )

    async def revisions(
        self, core_id: int, data: RuntimeSearch
    ) -> ServicePage[RuntimeRevisionOut]:
        await self.cores.get(core_id)
        limit = page_size(self.settings, data.per_page)
        result = await self.metadata.page(
            core_id, (data.page - 1) * limit, limit
        )
        return service_page(result, limit)

    async def commands(
        self, core_id: int, data: RuntimeSearch
    ) -> ServicePage[CoreRuntimeCommandModel]:
        await self.cores.get(core_id)
        result = await self.command_service.search(core_id, None, data)
        return result

    async def node_commands(
        self, code: str, key: str, data: RuntimeSearch
    ) -> ServicePage[CoreRuntimeCommandModel]:
        node = await self.nodes.authenticate(code, key)
        result = await self.command_service.actionable(node.id, data)
        return result

    async def due_command_ids(self, limit: int | None = None) -> list[int]:
        policy = self.settings.core_runtime
        if policy is None or not policy.enabled:
            return []
        result = await self.reader.due_ids(
            datetime.now(UTC).replace(tzinfo=None),
            min(limit or policy.scan_batch_size, policy.scan_batch_size),
        )
        return result
