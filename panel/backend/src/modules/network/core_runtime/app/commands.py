import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from hmac import compare_digest
from typing import Literal, cast

from papilio.errors.exceptions import ConflictException
from papilio.infra.db.tools.decorators import transactional

from src.config.settings import PapilioSettings
from src.modules.network.core_runtime.app.memberships import (
    InstalledProfileEncoding,
)
from src.modules.network.core_runtime.app.payloads import RuntimePayload
from src.modules.network.core_runtime.app.usage_encoding import (
    RuntimeUsageEncoding,
)
from src.modules.network.core_runtime.domain.dtos import (
    RuntimeAcknowledgement,
    RuntimeAction,
    RuntimeCapacity,
    RuntimeClaim,
    RuntimeCommandCreate,
    RuntimeRevisionCreate,
)
from src.modules.network.core_runtime.domain.models import (
    CoreRuntimeCommandModel,
    CoreRuntimeRevisionModel,
    CoreRuntimeStateModel,
)
from src.modules.network.core_runtime.infra.readers import (
    RuntimeSnapshotReader,
)
from src.modules.network.core_runtime.interfaces import (
    ICoreProvisioningBudgetQuery,
    ICoreUsagePolicyQuery,
    IRuntimeCommandService,
    IRuntimeRevisionService,
    IRuntimeStateService,
)
from src.modules.network.cores.domain.exports import CoreExportRequest
from src.modules.network.cores.interfaces import ICoreExportQuery, ICoreService
from src.modules.network.nodes.interfaces import INodeService


def conflict(code: str) -> ConflictException:
    return ConflictException(
        message=code.replace("_", " "), message_code=code, unique_dict={}
    )


def now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


class CoreRuntimeCommand:
    def __init__(
        self,
        states: IRuntimeStateService,
        revisions: IRuntimeRevisionService,
        commands: IRuntimeCommandService,
        cores: ICoreService,
        exports: ICoreExportQuery,
        nodes: INodeService,
        reader: RuntimeSnapshotReader,
        settings: PapilioSettings,
        budget: ICoreProvisioningBudgetQuery,
        usage_policy: ICoreUsagePolicyQuery,
    ) -> None:
        self.budget = budget
        self.usage_policy = usage_policy
        self.states, self.revisions, self.commands = (
            states,
            revisions,
            commands,
        )
        self.cores, self.exports, self.nodes, self.reader, self.settings = (
            cores,
            exports,
            nodes,
            reader,
            settings,
        )

    def policy(self) -> RuntimeCapacity:
        policy = self.settings.core_runtime
        if policy is None or not policy.enabled:
            raise conflict("runtime_disabled")
        return policy

    async def check_usage_admission(
        self, core_id: int, node_id: int, kind: str
    ) -> None:
        reason = await self.usage_policy.admission(core_id, node_id, kind)
        if reason is not None:
            raise conflict(reason)

    @staticmethod
    def check_revision(state: CoreRuntimeStateModel, expected: int) -> None:
        if state.revision != expected:
            raise conflict("runtime_revision_conflict")

    async def fingerprint(
        self, core_id: int, revision: CoreRuntimeRevisionModel | None = None
    ) -> tuple[str, str] | None:
        policy = self.policy()
        if revision is not None:
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
                return None
        facts = await self.reader.facts(
            core_id, policy.max_configurations + 1, policy.max_profiles + 1
        )
        if (
            len(facts.configurations) > policy.max_configurations
            or len(facts.profiles) > policy.max_profiles
        ):
            raise conflict("runtime_snapshot_capacity")
        if revision is not None and revision.encrypted_memberships is not None:
            members = await asyncio.to_thread(
                InstalledProfileEncoding.decode,
                revision.encrypted_memberships,
                self.settings.configuration_encryption_key,
            )
            try:
                facts = await asyncio.to_thread(
                    InstalledProfileEncoding.normalize_activation,
                    facts,
                    members,
                    now_utc(),
                )
            except ValueError:
                return None
        result = await asyncio.to_thread(
            RuntimePayload.fingerprints, facts, now_utc()
        )
        return result

    async def current_snapshot(
        self,
        revision: CoreRuntimeRevisionModel,
        entitlement_only: bool = False,
    ) -> None:
        fingerprints = await self.fingerprint(revision.core_id, revision)
        if fingerprints is None:
            raise conflict("runtime_snapshot_stale")
        snapshot, entitlements = fingerprints
        digest = entitlements if entitlement_only else snapshot
        expected = (
            revision.entitlement_sha256
            if entitlement_only
            else revision.snapshot_sha256
        )
        if not compare_digest(digest, expected):
            raise conflict("runtime_snapshot_stale")

    @transactional
    async def revision(
        self,
        core_id: int,
        data: RuntimeRevisionCreate,
        staff_id: int | None = None,
    ) -> CoreRuntimeRevisionModel:
        policy = self.policy()
        core = await self.cores.get(core_id)
        state = await self.states.locked(core_id)
        self.check_revision(state, data.expected_revision)
        capability = await self.usage_policy.capability(
            core_id, core.node_id, core.kind, current=True
        )
        if capability.protected_ports and not capability.available:
            raise conflict(
                capability.reason_code or "runtime_usage_isolation_required"
            )
        before = await self.fingerprint(core_id)
        exported = await self.exports.export(
            core_id, CoreExportRequest(mode=data.mode)
        )
        usage_policy = self.settings.core_usage
        usage_enabled = (
            usage_policy is not None
            and usage_policy.mode != "disabled"
            and core_id in usage_policy.stats_ports
        )
        if usage_enabled:
            assert usage_policy is not None
            capability = await self.usage_policy.capability(
                core_id, core.node_id, core.kind, current=True
            )
            if not capability.available:
                raise conflict(
                    capability.reason_code or "runtime_usage_unavailable"
                )
            facts = await self.reader.facts(
                core_id, policy.max_configurations + 1, policy.max_profiles + 1
            )
            try:
                exported = await asyncio.to_thread(
                    RuntimeUsageEncoding.decorate,
                    exported,
                    facts,
                    usage_policy,
                    self.settings.configuration_encryption_key,
                    capability.protected_ports,
                )
            except ValueError as error:
                raise conflict(str(error)) from error
        size = await asyncio.to_thread(
            lambda: len(exported.model_dump_json().encode("utf8"))
        )
        if size > policy.max_payload_bytes:
            raise conflict("runtime_payload_capacity")
        after = await self.fingerprint(core_id)
        if before is None or after is None or before != after:
            raise conflict("runtime_snapshot_stale")
        payload, digest = await asyncio.gather(
            asyncio.to_thread(
                RuntimePayload.encode,
                exported,
                self.settings.configuration_encryption_key,
            ),
            asyncio.to_thread(RuntimePayload.bundle_digest, exported),
        )
        membership_payload, membership_digest = None, None
        usage_payload, usage_digest = None, None
        membership_policy = self.settings.core_provisioning
        if (
            membership_policy is not None
            and membership_policy.mode != "disabled"
            and core.kind in ("xray", "sing_box")
        ):
            facts = await self.reader.facts(
                core_id, policy.max_configurations + 1, policy.max_profiles + 1
            )
            if len(facts.profiles) > membership_policy.max_memberships:
                raise conflict("runtime_membership_capacity")
            members = await asyncio.to_thread(
                InstalledProfileEncoding.capture,
                facts,
                exported,
                self.settings.configuration_encryption_key,
                now_utc(),
            )
            membership_payload, membership_digest = await asyncio.gather(
                asyncio.to_thread(
                    InstalledProfileEncoding.encode,
                    members,
                    self.settings.configuration_encryption_key,
                ),
                asyncio.to_thread(
                    InstalledProfileEncoding.membership_digest, members
                ),
            )
            if usage_enabled:
                assert usage_policy is not None
                try:
                    usage_snapshot = await asyncio.to_thread(
                        RuntimeUsageEncoding.capture,
                        exported,
                        members,
                        usage_policy,
                        capability.protected_ports,
                        facts,
                        self.settings.usage.policy,
                    )
                except ValueError as error:
                    raise conflict(str(error)) from error
                assert usage_snapshot is not None
                usage_payload, usage_digest = await asyncio.gather(
                    asyncio.to_thread(
                        RuntimeUsageEncoding.encode,
                        usage_snapshot,
                        self.settings.configuration_encryption_key,
                    ),
                    asyncio.to_thread(
                        RuntimeUsageEncoding.digest, usage_snapshot
                    ),
                )
        if usage_enabled and usage_payload is None:
            raise conflict("runtime_usage_membership_required")
        result = await self.revisions.create(
            CoreRuntimeRevisionModel(
                core_id=core_id,
                mode=data.mode,
                created_by_staff_id=staff_id,
                bundle_sha256=digest,
                snapshot_sha256=after[0],
                entitlement_sha256=after[1],
                artifact_count=len(exported.artifacts),
                encrypted_payload=payload,
                encrypted_memberships=membership_payload,
                membership_sha256=membership_digest,
                encrypted_usage=usage_payload,
                usage_sha256=usage_digest,
            )
        )
        await self.states.change(
            state, CoreRuntimeStateModel.patch(revision=state.revision + 1)
        )
        return result

    @transactional
    async def enqueue(
        self,
        core_id: int,
        data: RuntimeCommandCreate,
        staff_id: int | None = None,
        purpose: str = "operator",
    ) -> CoreRuntimeCommandModel:
        policy = self.policy()
        if purpose not in ("operator", "provisioning"):
            raise conflict("runtime_purpose_invalid")
        core = await self.cores.get(core_id)
        state = await self.states.locked(core_id)
        request_digest = await asyncio.to_thread(
            RuntimePayload.digest,
            data.model_dump_json(exclude={"expected_revision"}),
        )
        replay = await self.commands.by_key(core_id, data.request_key)
        if replay is not None:
            if (
                replay.request_sha256 != request_digest
                or replay.purpose != purpose
            ):
                raise conflict("runtime_request_conflict")
            return replay
        if (
            data.action in ("apply", "restart", "rollback")
            or data.reconcile_mode == "restore"
        ):
            await self.check_usage_admission(core_id, core.node_id, core.kind)
        self.check_revision(state, data.expected_revision)
        if (
            data.action not in ("validate", "stop", "reconcile")
            or data.reconcile_mode == "restore"
        ) and not policy.allow_start:
            raise conflict("runtime_start_disabled")
        outstanding = await self.commands.outstanding(core_id)
        if outstanding is not None:
            if data.action != "stop" or (
                outstanding.state == "leased"
                and outstanding.claim_until is not None
                and outstanding.claim_until > now_utc()
            ):
                raise conflict("runtime_command_busy")
            await self.commands.change(
                outstanding,
                CoreRuntimeCommandModel.patch(
                    state="failed",
                    error_code="runtime_superseded",
                    claim_hash=None,
                    claim_until=None,
                ),
            )
        revision_id = data.revision_id
        if data.action == "stop" or (
            data.action == "reconcile" and data.reconcile_mode == "observe"
        ):
            if revision_id is not None:
                raise conflict("runtime_revision_unexpected")
        else:
            if data.action == "restart":
                if (
                    revision_id is not None
                    and revision_id != state.applied_revision_id
                ):
                    raise conflict("runtime_revision_conflict")
                revision_id = state.applied_revision_id
            if revision_id is None:
                raise conflict("runtime_revision_required")
            revision = await self.revisions.get(revision_id, core_id)
            await self.current_snapshot(
                revision, data.action in ("rollback", "restart")
            )
        result = await self.commands.create(
            CoreRuntimeCommandModel(
                core_id=core_id,
                node_id=core.node_id,
                action=data.action,
                purpose=purpose,
                reconcile_mode=data.reconcile_mode,
                created_by_staff_id=staff_id,
                revision_id=revision_id,
                request_key=data.request_key,
                request_sha256=request_digest,
                reason=data.reason,
                available_at=now_utc(),
            )
        )
        patch = CoreRuntimeStateModel.patch(revision=state.revision + 1)
        if (
            data.action in ("apply", "rollback")
            or data.reconcile_mode == "restore"
        ):
            patch = CoreRuntimeStateModel.patch(
                revision=state.revision + 1, desired_revision_id=revision_id
            )
        if purpose == "operator":
            if data.action == "stop":
                patch.automation_paused = True
            elif (
                data.action in ("apply", "restart", "rollback")
                or data.reconcile_mode == "restore"
            ):
                patch.automation_paused = False
        await self.states.change(state, patch)
        return result

    @transactional
    async def claim(
        self, code: str, key: str, command_id: int
    ) -> RuntimeClaim:
        policy = self.policy()
        node = await self.nodes.authenticate(code, key)
        task = await self.commands.get(command_id)
        if task.node_id != node.id:
            raise conflict("runtime_node_mismatch")
        core = await self.cores.get(task.core_id)
        state = await self.states.locked(core.id)
        task = await self.commands.locked_get(command_id)
        now = now_utc()
        if (
            task.available_at > now
            or task.state not in ("queued", "leased")
            or (
                task.state == "leased"
                and task.claim_until is not None
                and task.claim_until > now
            )
        ):
            raise conflict("runtime_not_claimable")
        if task.attempts >= policy.max_attempts:
            raise conflict("runtime_attempts_exhausted")
        if (
            task.action in ("apply", "restart", "rollback")
            or task.reconcile_mode == "restore"
        ):
            await self.check_usage_admission(core.id, core.node_id, core.kind)
        if task.purpose == "provisioning" and task.revision_id is not None:
            budget = await self.budget.current(core.id, task.revision_id)
            if budget.exhausted:
                raise conflict("runtime_provision_attempts_exhausted")
            if budget.retry_at is not None and budget.retry_at > now:
                raise conflict("runtime_retry_pending")
        if (
            task.action not in ("validate", "stop", "reconcile")
            or task.reconcile_mode == "restore"
        ) and (not policy.allow_start or not node.is_enabled):
            raise conflict("runtime_start_disabled")
        artifacts = []
        digest = None
        memberships, membership_sha256 = None, None
        usage, usage_sha256 = None, None
        if task.revision_id is not None:
            revision = await self.revisions.get(task.revision_id, core.id)
            await self.current_snapshot(
                revision, task.action in ("rollback", "restart")
            )
            export = await asyncio.to_thread(
                RuntimePayload.decode,
                revision.encrypted_payload,
                self.settings.configuration_encryption_key,
            )
            artifacts, digest = export.artifacts, revision.bundle_sha256
            if revision.encrypted_memberships is not None:
                members = await asyncio.to_thread(
                    InstalledProfileEncoding.decode,
                    revision.encrypted_memberships,
                    self.settings.configuration_encryption_key,
                )
                memberships, membership_sha256 = (
                    members.memberships,
                    revision.membership_sha256,
                )
            if revision.encrypted_usage is not None:
                usage = await asyncio.to_thread(
                    RuntimeUsageEncoding.decode,
                    revision.encrypted_usage,
                    self.settings.configuration_encryption_key,
                )
                usage_sha256 = revision.usage_sha256
        token = secrets.token_urlsafe(32)
        claim_hash = await asyncio.to_thread(RuntimePayload.digest, token)
        until = now + timedelta(seconds=policy.claim_seconds)
        await self.commands.change(
            task,
            CoreRuntimeCommandModel.patch(
                state="leased",
                attempts=task.attempts + 1,
                claim_hash=claim_hash,
                claim_until=until,
                ack_sha256=None,
            ),
        )
        await self.states.change(
            state, CoreRuntimeStateModel.patch(revision=state.revision + 1)
        )
        return RuntimeClaim(
            command_id=task.id,
            core_id=core.id,
            core_kind=core.kind,
            action=cast(RuntimeAction, task.action),
            reconcile_mode=cast(
                Literal["observe", "restore"] | None, task.reconcile_mode
            ),
            revision_id=task.revision_id,
            bundle_sha256=digest,
            claim_token=token,
            claim_until=until.replace(tzinfo=UTC),
            artifacts=artifacts,
            memberships=memberships,
            membership_sha256=membership_sha256,
            usage=usage,
            usage_sha256=usage_sha256,
        )

    @transactional
    async def acknowledge(
        self,
        code: str,
        key: str,
        command_id: int,
        data: RuntimeAcknowledgement,
    ) -> CoreRuntimeCommandModel:
        self.policy()
        node = await self.nodes.authenticate(code, key)
        task = await self.commands.get(command_id)
        if task.node_id != node.id:
            raise conflict("runtime_node_mismatch")
        state = await self.states.locked(task.core_id)
        task = await self.commands.locked_get(command_id)
        token_hash, ack_digest = await asyncio.gather(
            asyncio.to_thread(RuntimePayload.digest, data.claim_token),
            asyncio.to_thread(
                RuntimePayload.digest,
                data.model_dump_json(
                    exclude={
                        name
                        for name in ("usage_sha256", "process_epoch")
                        if getattr(data, name) is None
                    }
                ),
            ),
        )
        if task.claim_hash is None or not compare_digest(
            token_hash, task.claim_hash
        ):
            raise conflict("runtime_lease_mismatch")
        if task.state in ("succeeded", "failed"):
            if task.ack_sha256 != ack_digest:
                raise conflict("runtime_ack_conflict")
            return task
        if (
            task.state != "leased"
            or task.claim_until is None
            or task.claim_until <= now_utc()
        ):
            raise conflict("runtime_lease_expired")
        observed = None
        if data.observed_revision_id is not None:
            observed = await self.revisions.get(
                data.observed_revision_id, task.core_id
            )
        if (
            observed is not None
            and observed.bundle_sha256 != data.bundle_sha256
        ):
            raise conflict("runtime_checksum_mismatch")
        if observed is None and data.bundle_sha256 is not None:
            raise conflict("runtime_checksum_mismatch")
        if data.usage_sha256 != (
            observed.usage_sha256 if observed is not None else None
        ):
            raise conflict("runtime_usage_checksum_mismatch")
        if (
            data.observed_status == "running"
            and observed is not None
            and observed.usage_sha256 is not None
            and data.process_epoch is None
        ) or (
            data.observed_status != "running"
            and data.process_epoch is not None
        ):
            raise conflict("runtime_process_epoch_invalid")
        if data.outcome == "succeeded" and (
            task.action in ("apply", "restart", "rollback")
            or task.reconcile_mode == "restore"
        ):
            core = await self.cores.get(task.core_id)
            reason = await self.usage_policy.admission(
                core.id, core.node_id, core.kind
            )
            if reason is not None:
                await self.states.change(
                    state,
                    CoreRuntimeStateModel.patch(
                        revision=state.revision + 1,
                        observed_status="unknown",
                        observed_process_epoch=None,
                    ),
                )
                result = await self.commands.change(
                    task,
                    CoreRuntimeCommandModel.patch(
                        state="failed",
                        error_code=reason,
                        ack_sha256=ack_digest,
                    ),
                )
                return result
        current_fingerprints = None
        if data.observed_status == "running":
            if observed is None:
                raise conflict("runtime_ack_invalid")
            current_fingerprints = await self.fingerprint(
                task.core_id, observed
            )
            if (
                current_fingerprints is None
                or current_fingerprints[1] != observed.entitlement_sha256
            ):
                await self.states.change(
                    state,
                    CoreRuntimeStateModel.patch(
                        revision=state.revision + 1,
                        observed_status="unknown",
                        observed_process_epoch=None,
                    ),
                )
                result = await self.commands.change(
                    task,
                    CoreRuntimeCommandModel.patch(
                        state="failed",
                        error_code="runtime_snapshot_stale",
                        ack_sha256=ack_digest,
                    ),
                )
                return result
        patch = CoreRuntimeStateModel.patch(
            revision=state.revision + 1,
            observed_status=data.observed_status,
            observed_process_epoch=data.process_epoch,
        )
        if data.outcome == "succeeded":
            if task.action == "stop":
                if data.observed_status != "stopped":
                    raise conflict("runtime_ack_invalid")
            elif task.action == "validate":
                if task.revision_id is None:
                    raise conflict("runtime_ack_invalid")
                patch = CoreRuntimeStateModel.patch(
                    revision=state.revision + 1,
                    validated_revision_id=task.revision_id,
                    observed_status=data.observed_status,
                )
            elif (
                task.action == "reconcile" and task.reconcile_mode == "observe"
            ):
                patch = CoreRuntimeStateModel.patch(
                    revision=state.revision + 1,
                    observed_status=data.observed_status,
                )
            else:
                if task.revision_id is None:
                    raise conflict("runtime_ack_invalid")
                if (
                    data.observed_status != "running"
                    or data.observed_revision_id != task.revision_id
                ):
                    raise conflict("runtime_ack_invalid")
                revision = await self.revisions.get(
                    task.revision_id, task.core_id
                )
                if current_fingerprints is None:
                    current_fingerprints = await self.fingerprint(
                        task.core_id, revision
                    )
                snapshot, entitlements = current_fingerprints or (None, None)
                expected = (
                    revision.entitlement_sha256
                    if task.action in ("rollback", "restart")
                    else revision.snapshot_sha256
                )
                actual = (
                    entitlements
                    if task.action in ("rollback", "restart")
                    else snapshot
                )
                if actual != expected:
                    await self.states.change(
                        state,
                        CoreRuntimeStateModel.patch(
                            revision=state.revision + 1,
                            observed_status="unknown",
                            observed_process_epoch=None,
                        ),
                    )
                    result = await self.commands.change(
                        task,
                        CoreRuntimeCommandModel.patch(
                            state="failed",
                            error_code="runtime_snapshot_stale",
                            ack_sha256=ack_digest,
                        ),
                    )
                    return result
                patch = CoreRuntimeStateModel.patch(
                    revision=state.revision + 1,
                    applied_revision_id=task.revision_id,
                    observed_status="running",
                )
        elif (
            data.observed_revision_id is not None
            and data.observed_revision_id != state.applied_revision_id
        ):
            if data.observed_revision_id != task.revision_id:
                raise conflict("runtime_ack_invalid")
            if data.observed_status not in ("stopped", "unknown"):
                raise conflict("runtime_ack_invalid")
        patch.last_observed_at = now_utc()
        patch.observed_process_epoch = data.process_epoch
        await self.states.change(state, patch)
        result = await self.commands.change(
            task,
            CoreRuntimeCommandModel.patch(
                state=data.outcome,
                error_code=data.error_code,
                ack_sha256=ack_digest,
            ),
        )
        return result

    @transactional
    async def recover(self, command_id: int) -> CoreRuntimeCommandModel:
        policy = self.policy()
        task = await self.commands.get(command_id)
        state = await self.states.locked(task.core_id)
        task = await self.commands.locked_get(command_id)
        if (
            task.state != "leased"
            or task.claim_until is None
            or task.claim_until > now_utc()
        ):
            return task
        exhausted = task.attempts >= policy.max_attempts
        retry_seconds = policy.retry_seconds
        if task.purpose == "provisioning" and task.revision_id is not None:
            budget = await self.budget.current(task.core_id, task.revision_id)
            exhausted = exhausted or budget.exhausted
            provision_policy = self.settings.core_provisioning
            if provision_policy is not None:
                retry_seconds = max(
                    retry_seconds, provision_policy.retry_seconds
                )
        result = await self.commands.change(
            task,
            CoreRuntimeCommandModel.patch(
                state="failed" if exhausted else "queued",
                error_code="runtime_attempts_exhausted" if exhausted else None,
                claim_hash=None,
                claim_until=None,
                available_at=now_utc() + timedelta(seconds=retry_seconds),
            ),
        )
        await self.states.change(
            state,
            CoreRuntimeStateModel.patch(
                revision=state.revision + 1,
                observed_status="unknown",
                observed_process_epoch=None,
            ),
        )
        return result
