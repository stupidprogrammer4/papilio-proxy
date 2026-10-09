from datetime import UTC, datetime, timedelta

from papilio.infra.db.tools.decorators import transactional

from src.config.settings import PapilioSettings
from src.modules.network.core_runtime.domain.dtos import (
    RuntimeCommandCreate,
    RuntimeRevisionCreate,
)
from src.modules.network.core_runtime.domain.memberships import (
    CoreProvisioningDecision,
)
from src.modules.network.core_runtime.domain.models import (
    CoreRuntimeCommandModel,
    CoreRuntimeStateModel,
)
from src.modules.network.core_runtime.infra.provisioning import (
    CoreProvisioningReader,
)
from src.modules.network.core_runtime.interfaces import (
    ICoreProvisioningBudgetQuery,
    ICoreRuntimeCommand,
    ICoreUsagePolicyQuery,
    IInstalledProfileQuery,
    IRuntimeCommandService,
    IRuntimeStateService,
)
from src.modules.network.cores.interfaces import ICoreService
from src.modules.network.nodes.interfaces import INodeService


class CoreProvisioningQuery:
    def __init__(
        self, reader: CoreProvisioningReader, settings: PapilioSettings
    ) -> None:
        self.reader, self.settings = reader, settings

    async def due_core_ids(self, limit: int | None = None) -> list[int]:
        policy = self.settings.core_provisioning
        if policy is None or policy.mode == "disabled":
            return []
        capacity = min(limit or policy.batch_size, policy.batch_size)
        result = await self.reader.due_core_ids(
            datetime.now(UTC).replace(tzinfo=None, microsecond=0),
            ["queued", "failed", "leased"],
            ["dispatching", "active", "revoking"],
            capacity,
        )
        return result


class CoreProvisioningCommand:
    def __init__(
        self,
        states: IRuntimeStateService,
        commands: IRuntimeCommandService,
        runtime: ICoreRuntimeCommand,
        cores: ICoreService,
        settings: PapilioSettings,
        installed: IInstalledProfileQuery,
        nodes: INodeService,
        budget: ICoreProvisioningBudgetQuery,
        usage: ICoreUsagePolicyQuery,
    ) -> None:
        self.usage = usage
        self.installed = installed
        self.nodes = nodes
        self.budget = budget
        self.states, self.commands, self.runtime, self.cores, self.settings = (
            states,
            commands,
            runtime,
            cores,
            settings,
        )

    @transactional
    async def ensure(self, core_id: int) -> CoreProvisioningDecision:
        policy = self.settings.core_provisioning
        if policy is None or policy.mode == "disabled":
            return CoreProvisioningDecision(
                core_id=core_id,
                state="blocked",
                reason_code="core_provisioning_disabled",
            )
        core = await self.cores.get(core_id)
        state = await self.states.locked(core_id)
        await self.states.change(
            state,
            CoreRuntimeStateModel.patch(
                last_provision_scan_at=datetime.now(UTC).replace(
                    tzinfo=None, microsecond=0
                )
            ),
        )
        node = await self.nodes.get(core.node_id)
        result = await self._decide(
            core_id, core.kind, core.node_id, node.is_enabled, state
        )
        return result

    async def _decide(
        self,
        core_id: int,
        kind: str,
        node_id: int,
        node_enabled: bool,
        state: CoreRuntimeStateModel,
    ) -> CoreProvisioningDecision:
        policy = self.settings.core_provisioning
        assert policy is not None
        runtime_policy = self.settings.core_runtime
        if policy.mode == "enforced":
            return CoreProvisioningDecision(
                core_id=core_id,
                state="blocked",
                reason_code="runtime_enforcement_unavailable",
            )
        if (
            runtime_policy is None
            or not runtime_policy.enabled
            or not runtime_policy.allow_start
        ):
            return CoreProvisioningDecision(
                core_id=core_id,
                state="blocked",
                reason_code="runtime_start_disabled",
            )
        if kind not in ("xray", "sing_box"):
            return CoreProvisioningDecision(
                core_id=core_id,
                state="blocked",
                reason_code="runtime_kind_unavailable",
            )
        if not node_enabled:
            return CoreProvisioningDecision(
                core_id=core_id,
                state="blocked",
                reason_code="runtime_node_disabled",
            )
        if state.automation_paused:
            return CoreProvisioningDecision(
                core_id=core_id,
                state="blocked",
                reason_code="runtime_automation_paused",
            )
        outstanding = await self.commands.outstanding(core_id)
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        if outstanding is not None:
            expired = (
                outstanding.state == "leased"
                and outstanding.claim_until is not None
                and outstanding.claim_until <= now
            )
            stale = (
                outstanding.revision_id is not None
                and not await self.installed.matches_current(
                    core_id, outstanding.revision_id
                )
            )
            exhausted = False
            if (
                outstanding.purpose == "provisioning"
                and outstanding.state == "queued"
                and outstanding.revision_id is not None
            ):
                budget = await self.budget.current(
                    core_id, outstanding.revision_id
                )
                exhausted = budget.exhausted
            if outstanding.purpose == "provisioning" and (
                expired
                or exhausted
                or (outstanding.state == "queued" and stale)
            ):
                await self.commands.change(
                    outstanding,
                    CoreRuntimeCommandModel.patch(
                        state="failed",
                        error_code=(
                            "runtime_provision_attempts_exhausted"
                            if exhausted
                            else "runtime_superseded"
                        ),
                        claim_hash=None,
                        claim_until=None,
                    ),
                )
                await self.states.change(
                    state,
                    CoreRuntimeStateModel.patch(revision=state.revision + 1),
                )
            else:
                return CoreProvisioningDecision(
                    core_id=core_id,
                    state="waiting",
                    reason_code="runtime_command_outstanding",
                    command_id=outstanding.id,
                    revision_id=outstanding.revision_id,
                )
        if (
            state.applied_revision_id is not None
            and await self.installed.matches_current(
                core_id, state.applied_revision_id
            )
        ):
            if state.observed_status == "running":
                if (
                    state.last_observed_at is not None
                    and state.last_observed_at
                    + timedelta(seconds=policy.observation_seconds)
                    > now
                ):
                    return CoreProvisioningDecision(
                        core_id=core_id,
                        state="installed",
                        revision_id=state.applied_revision_id,
                    )
                observation = await self.runtime.enqueue(
                    core_id,
                    RuntimeCommandCreate(
                        expected_revision=state.revision,
                        action="reconcile",
                        reconcile_mode="observe",
                        request_key=f"provisioning:observe:{core_id}:{state.revision}",
                        reason="Refresh installed subscription observation",
                    ),
                    purpose="provisioning",
                )
                return CoreProvisioningDecision(
                    core_id=core_id,
                    state="queued",
                    command_id=observation.id,
                    revision_id=state.applied_revision_id,
                )
        reason = await self.usage.admission(core_id, node_id, kind)
        if reason is not None:
            return CoreProvisioningDecision(
                core_id=core_id,
                state="blocked",
                reason_code=reason,
                revision_id=state.desired_revision_id,
            )
        revision_id = state.desired_revision_id
        if revision_id is None or not await self.installed.matches_current(
            core_id, revision_id
        ):
            revision = await self.runtime.revision(
                core_id,
                RuntimeRevisionCreate(
                    expected_revision=state.revision, mode="merged"
                ),
            )
            revision_id = revision.id
        budget = await self.budget.current(core_id, revision_id)
        if budget.exhausted or (
            budget.retry_at is not None and budget.retry_at > now
        ):
            return CoreProvisioningDecision(
                core_id=core_id,
                state="blocked",
                reason_code=(
                    "runtime_provision_attempts_exhausted"
                    if budget.exhausted
                    else "runtime_retry_pending"
                ),
                revision_id=revision_id,
            )
        state = await self.states.locked(core_id)
        queued = await self.runtime.enqueue(
            core_id,
            RuntimeCommandCreate(
                expected_revision=state.revision,
                action="apply",
                revision_id=revision_id,
                request_key=(
                    f"provisioning:{core_id}:{revision_id}:{state.revision}"
                ),
                reason="Install prepared subscription memberships",
            ),
            purpose="provisioning",
        )
        return CoreProvisioningDecision(
            core_id=core_id,
            state="queued",
            command_id=queued.id,
            revision_id=revision_id,
        )
