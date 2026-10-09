import asyncio
from datetime import timedelta
from hmac import compare_digest

from src.config.settings import PapilioSettings
from src.modules.network.core_runtime.app.commands import conflict, now_utc
from src.modules.network.core_runtime.app.usage_encoding import (
    RuntimeUsageEncoding,
)
from src.modules.network.core_runtime.interfaces import (
    IInstalledProfileQuery,
    IRuntimeCommandService,
    IRuntimeRevisionService,
    IRuntimeStateService,
)


class InstalledUsageQuery:
    def __init__(
        self,
        states: IRuntimeStateService,
        revisions: IRuntimeRevisionService,
        installed: IInstalledProfileQuery,
        settings: PapilioSettings,
        commands: IRuntimeCommandService,
    ) -> None:
        self.commands = commands
        self.states, self.revisions, self.installed, self.settings = (
            states,
            revisions,
            installed,
            settings,
        )

    def required(self, core_id: int) -> bool:
        policy = self.settings.core_usage
        return (
            policy is not None
            and policy.mode != "disabled"
            and core_id in policy.stats_ports
        )

    async def lock_core(self, core_id: int) -> None:
        await self.states.lock_core(core_id)

    async def allocation_guard(self, core_id: int) -> None:
        policy = self.settings.core_usage
        if policy is None or policy.mode == "disabled":
            return
        command = await self.commands.outstanding(core_id)
        if command is not None and (
            command.action in ("apply", "restart", "rollback")
            or command.reconcile_mode == "restore"
        ):
            raise conflict("runtime_usage_replacement_pending")

    async def proof(
        self,
        core_id: int,
        node_id: int,
        profile_id: int,
        subscription_id: int,
        generation: int,
        configuration_revision: int,
        revision_id: int,
        usage_sha256: str,
        process_epoch: str,
    ) -> None:
        policy = self.settings.core_usage
        if (
            policy is None
            or policy.mode == "disabled"
            or core_id not in policy.stats_ports
        ):
            raise conflict("runtime_usage_unavailable")
        state = await self.states.current(core_id)
        if (
            state is None
            or state.automation_paused
            or state.observed_status != "running"
            or state.applied_revision_id != revision_id
            or state.observed_process_epoch != process_epoch
            or state.last_observed_at is None
            or state.last_observed_at
            + timedelta(seconds=policy.observation_seconds)
            <= now_utc()
        ):
            raise conflict("runtime_usage_installation_pending")
        revision = await self.revisions.get(revision_id, core_id)
        if (
            revision.encrypted_usage is None
            or revision.usage_sha256 != usage_sha256
        ):
            raise conflict("runtime_usage_proof_invalid")
        snapshot = await asyncio.to_thread(
            RuntimeUsageEncoding.decode,
            revision.encrypted_usage,
            self.settings.configuration_encryption_key,
        )
        actual = await asyncio.to_thread(RuntimeUsageEncoding.digest, snapshot)
        if (
            not compare_digest(actual, usage_sha256)
            or len(snapshot.profiles) > policy.max_profiles
        ):
            raise conflict("runtime_usage_proof_invalid")
        member = next(
            (
                item
                for item in snapshot.profiles
                if item.profile_id == profile_id
            ),
            None,
        )
        if (
            member is None
            or member.subscription_id != subscription_id
            or member.generation != generation
            or member.configuration_revision != configuration_revision
        ):
            raise conflict("runtime_usage_profile_invalid")
        if not await self.installed.matches_current(core_id, revision_id):
            raise conflict("runtime_usage_snapshot_stale")
