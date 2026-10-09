import asyncio
from datetime import timedelta
from hmac import compare_digest

from src.config.settings import PapilioSettings
from src.modules.network.core_runtime.app.commands import conflict, now_utc
from src.modules.network.core_runtime.app.memberships import (
    InstalledProfileEncoding,
)
from src.modules.network.core_runtime.app.payloads import RuntimePayload
from src.modules.network.core_runtime.app.usage_encoding import (
    RuntimeUsageEncoding,
)
from src.modules.network.core_runtime.domain.memberships import (
    InstalledProfileProof,
)
from src.modules.network.core_runtime.infra.readers import (
    RuntimeSnapshotReader,
)
from src.modules.network.core_runtime.interfaces import (
    ICoreUsagePolicyQuery,
    IRuntimeRevisionService,
    IRuntimeStateService,
)
from src.modules.network.cores.interfaces import ICoreService


class InstalledProfileQuery:
    def __init__(
        self,
        states: IRuntimeStateService,
        revisions: IRuntimeRevisionService,
        reader: RuntimeSnapshotReader,
        settings: PapilioSettings,
        usage_policy: ICoreUsagePolicyQuery,
        cores: ICoreService,
    ) -> None:
        self.states, self.revisions, self.reader, self.settings = (
            states,
            revisions,
            reader,
            settings,
        )
        self.usage_policy, self.cores = usage_policy, cores

    async def lock_core(self, core_id: int) -> None:
        await self.states.lock_core(core_id)

    async def lock_cores(self, core_ids: list[int]) -> None:
        await self.states.lock_cores(core_ids)

    async def matches_current(self, core_id: int, revision_id: int) -> bool:
        runtime = self.settings.core_runtime
        if runtime is None or not runtime.enabled:
            return False
        revision = await self.revisions.get(revision_id, core_id)
        core = await self.cores.get(core_id)
        capability = await self.usage_policy.capability(
            core_id, core.node_id, core.kind, current=True
        )
        usage = None
        if revision.encrypted_usage is not None:
            usage = await asyncio.to_thread(
                RuntimeUsageEncoding.decode,
                revision.encrypted_usage,
                self.settings.configuration_encryption_key,
            )
        if not RuntimeUsageEncoding.compatible(
            usage,
            core_id,
            self.settings.core_usage,
            capability.protected_ports,
        ):
            return False
        if revision.encrypted_memberships is None:
            return False
        snapshot = await asyncio.to_thread(
            InstalledProfileEncoding.decode,
            revision.encrypted_memberships,
            self.settings.configuration_encryption_key,
        )
        facts = await self.reader.facts(
            core_id, runtime.max_configurations + 1, runtime.max_profiles + 1
        )
        if (
            len(facts.configurations) > runtime.max_configurations
            or len(facts.profiles) > runtime.max_profiles
        ):
            return False
        try:
            normalized = await asyncio.to_thread(
                InstalledProfileEncoding.normalize_activation,
                facts,
                snapshot,
                now_utc(),
            )
        except ValueError:
            return False
        fingerprint = await asyncio.to_thread(
            RuntimePayload.fingerprints, normalized, now_utc()
        )
        return compare_digest(fingerprint[0], revision.snapshot_sha256)

    async def proof(
        self,
        core_id: int,
        profile_id: int,
        generation: int,
        configuration_revision: int,
        action: str,
        credential_sha256: str,
    ) -> InstalledProfileProof:
        policy = self.settings.core_provisioning
        runtime = self.settings.core_runtime
        if policy is None or policy.mode == "disabled":
            raise conflict("core_provisioning_disabled")
        if policy.mode == "enforced":
            raise conflict("runtime_enforcement_unavailable")
        state = await self.states.current(core_id)
        now = now_utc()
        if (
            runtime is None
            or not runtime.enabled
            or state is None
            or state.automation_paused
            or state.applied_revision_id is None
            or state.observed_status != "running"
            or state.last_observed_at is None
            or state.last_observed_at
            + timedelta(seconds=policy.observation_seconds)
            <= now
        ):
            raise conflict("provision_runtime_pending")
        revision = await self.revisions.get(state.applied_revision_id, core_id)
        if (
            revision.encrypted_memberships is None
            or revision.membership_sha256 is None
        ):
            raise conflict("provision_runtime_membership_unavailable")
        snapshot = await asyncio.to_thread(
            InstalledProfileEncoding.decode,
            revision.encrypted_memberships,
            self.settings.configuration_encryption_key,
        )
        if len(snapshot.memberships) > policy.max_memberships:
            raise conflict("runtime_membership_capacity")
        digest = await asyncio.to_thread(
            InstalledProfileEncoding.membership_digest, snapshot
        )
        if not compare_digest(digest, revision.membership_sha256):
            raise conflict("runtime_membership_invalid")
        membership = next(
            (
                row
                for row in snapshot.memberships
                if row.profile_id == profile_id
            ),
            None,
        )
        if (
            membership is None
            or membership.generation != generation
            or membership.configuration_revision != configuration_revision
            or membership.presence
            != ("present" if action == "apply" else "absent")
            or not compare_digest(
                membership.credential_sha256, credential_sha256
            )
        ):
            raise conflict("provision_runtime_pending")
        facts = await self.reader.facts(
            core_id, runtime.max_configurations + 1, runtime.max_profiles + 1
        )
        if (
            len(facts.configurations) > runtime.max_configurations
            or len(facts.profiles) > runtime.max_profiles
        ):
            raise conflict("runtime_snapshot_capacity")
        try:
            normalized = await asyncio.to_thread(
                InstalledProfileEncoding.normalize_activation,
                facts,
                snapshot,
                now,
            )
        except ValueError as exc:
            raise conflict("runtime_snapshot_stale") from exc
        fingerprints = await asyncio.to_thread(
            RuntimePayload.fingerprints, normalized, now
        )
        if not compare_digest(fingerprints[1], revision.entitlement_sha256):
            raise conflict("runtime_snapshot_stale")
        return InstalledProfileProof(
            installed_revision_id=revision.id,
            membership_sha256=digest,
            membership=membership,
        )
