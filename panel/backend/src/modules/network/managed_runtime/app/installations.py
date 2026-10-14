"""Native leased CLOSED installation proof; never authorizes traffic."""

import asyncio
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from hmac import compare_digest

from papilio.errors.exceptions import ConflictException, NotFoundException
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import encrypt

from src.config.settings import PapilioSettings
from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.network.core_runtime.app.payloads import RuntimePayload
from src.modules.network.core_runtime.infra.readers import (
    RuntimeSnapshotReader,
)
from src.modules.network.core_runtime.interfaces import (
    IRuntimeCommandService,
    IRuntimeRevisionService,
    IRuntimeStateService,
)
from src.modules.network.cores.interfaces import ICoreService
from src.modules.network.managed_runtime.app.admission_membership import (
    ManagedAdmissionMembership,
)
from src.modules.network.managed_runtime.app.installation_encoding import (
    ManagedInstallationEncoding,
)
from src.modules.network.managed_runtime.app.wire_encoding import (
    ManagedWireEncoding,
)
from src.modules.network.managed_runtime.domain.installations import (
    ManagedAdapterPolicy,
    ManagedClosedStartupAcknowledgement,
    ManagedInstallationClaim,
    ManagedInstallationCreate,
    ManagedInstallationExpectation,
    ManagedInstalledClosedOut,
)
from src.modules.network.managed_runtime.domain.models import (
    ManagedEpochModel,
    ManagedInstallationModel,
)
from src.modules.network.managed_runtime.domain.rollovers import (
    ManagedEpochRolloverOut,
    ManagedEpochRolloverSubmission,
)
from src.modules.network.managed_runtime.domain.scopes import (
    ManagedInstallationScope,
)
from src.modules.network.managed_runtime.infra.epoch_seal_reads import (
    ManagedEpochSealReader,
)
from src.modules.network.managed_runtime.infra.scopes import (
    ManagedInstallationScopeReader,
)
from src.modules.network.managed_runtime.interfaces import (
    IManagedEpochSealService,
    IManagedEpochService,
    IManagedInstallationService,
)
from src.modules.network.nodes.interfaces import INodeService


def conflict(code: str) -> ConflictException:
    return ConflictException(
        unique_dict={},
        message="Managed installation rejected.",
        message_code=code,
    )


class ManagedInstallationCommand:
    def __init__(
        self,
        installations: IManagedInstallationService,
        epochs: IManagedEpochService,
        nodes: INodeService,
        cores: ICoreService,
        states: IRuntimeStateService,
        revisions: IRuntimeRevisionService,
        commands: IRuntimeCommandService,
        reader: RuntimeSnapshotReader,
        settings: PapilioSettings,
        scopes: ManagedInstallationScopeReader,
        customers: ICustomerService,
        epoch_seals: IManagedEpochSealService,
        epoch_reader: ManagedEpochSealReader,
    ) -> None:
        self.installations, self.epochs = installations, epochs
        self.nodes, self.cores, self.states, self.revisions = (
            nodes,
            cores,
            states,
            revisions,
        )
        self.commands = commands
        self.reader, self.settings = reader, settings
        self.scopes, self.customers = scopes, customers
        self.epoch_seals, self.epoch_reader = epoch_seals, epoch_reader

    @staticmethod
    def rollover_digest(data: ManagedEpochRolloverSubmission) -> str:
        payload = data.model_dump_json().encode()
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def rollover_original_matches(
        data: ManagedEpochRolloverSubmission,
    ) -> bool:
        payload = data.original_receipt.encode()
        return (
            len(payload) == data.receipt.bytes
            and hashlib.sha256(payload).hexdigest()
            == data.receipt.receipt_sha256
            and data.receipt.epoch != ""
        )

    @staticmethod
    def rollover_output(
        previous: ManagedEpochModel, current: ManagedEpochModel
    ) -> ManagedEpochRolloverOut:
        if (
            current.rollover_request_id is None
            or current.rollover_request_sha256 is None
            or current.previous_epoch_id != previous.id
        ):
            raise conflict("managed_rollover_record_unresolved")
        return ManagedEpochRolloverOut(
            installation_id=current.installation_id,
            previous_epoch_id=previous.id,
            previous_process_epoch=previous.process_epoch,
            epoch_id=current.id,
            process_epoch=current.process_epoch,
            request_id=current.rollover_request_id,
            request_sha256=current.rollover_request_sha256,
            receipt_sha256=current.receipt_sha256,
            observed_at=current.installed_closed_at.replace(tzinfo=UTC),
        )

    async def initial_scope(self, core_id: int) -> ManagedInstallationScope:
        runtime = self.settings.core_runtime
        if runtime is None:
            raise conflict("managed_runtime_start_disabled")
        scope = await self.scopes.initial(core_id, runtime.max_profiles + 1)
        if len(scope.profiles) > runtime.max_profiles:
            raise conflict("managed_runtime_snapshot_capacity")
        await self.customers.locked_many(
            sorted(
                {
                    customer_id
                    for owner in scope.owners
                    for customer_id in (
                        owner.customer_id,
                        owner.payer_customer_id or owner.customer_id,
                    )
                }
            )
        )
        return scope

    async def lock_scope(
        self, core_id: int, scope: ManagedInstallationScope
    ) -> None:
        runtime = self.settings.core_runtime
        if runtime is None:
            raise conflict("managed_runtime_start_disabled")
        owners = await self.scopes.lock_subscriptions(
            [owner.subscription_id for owner in scope.owners]
        )
        if owners != scope.owners:
            raise conflict("managed_installation_scope_changed")
        configurations = await self.scopes.lock_configurations(
            core_id, runtime.max_configurations + 1
        )
        if len(configurations) > runtime.max_configurations:
            raise conflict("managed_runtime_snapshot_capacity")
        profiles = await self.scopes.current_profiles(
            configurations, runtime.max_profiles + 1
        )
        if profiles != scope.profiles:
            raise conflict("managed_installation_scope_changed")

    def policy(self) -> ManagedAdapterPolicy:
        policy = self.settings.managed_adapter
        if policy is None or not policy.enabled:
            raise conflict("managed_adapter_disabled")
        runtime = self.settings.core_runtime
        if runtime is None or not runtime.enabled or not runtime.allow_start:
            raise conflict("managed_runtime_start_disabled")
        return policy

    async def current_expectation(
        self, row: ManagedInstallationModel, policy: ManagedAdapterPolicy
    ) -> ManagedInstallationExpectation:
        revision = await self.revisions.get(
            row.runtime_revision_id, row.core_id
        )
        state = await self.states.current(row.core_id)
        runtime = self.settings.core_runtime
        if (
            state is None
            or state.automation_paused
            or runtime is None
            or revision.encrypted_memberships is None
            or revision.membership_sha256 is None
        ):
            raise conflict("managed_runtime_revision_stale")
        if row.encrypted_manifest:
            issued = await asyncio.to_thread(
                ManagedInstallationEncoding.decode,
                row.encrypted_manifest,
                self.settings.configuration_encryption_key,
            )
            if issued.runtime_state_revision != state.revision:
                raise conflict("managed_runtime_revision_stale")
        facts = await self.reader.facts(
            row.core_id,
            runtime.max_configurations + 1,
            runtime.max_profiles + 1,
        )
        if (
            len(facts.configurations) > runtime.max_configurations
            or len(facts.profiles) > runtime.max_profiles
        ):
            raise conflict("managed_runtime_snapshot_capacity")
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        try:
            await asyncio.to_thread(
                ManagedAdmissionMembership.verify,
                facts,
                revision.encrypted_memberships,
                revision.membership_sha256,
                revision.snapshot_sha256,
                now,
                self.settings.configuration_encryption_key,
            )
        except ValueError:
            raise conflict("managed_runtime_snapshot_stale") from None
        try:
            expectation = await asyncio.to_thread(
                ManagedInstallationEncoding.derive,
                revision.id,
                state.revision,
                revision.encrypted_payload,
                revision.encrypted_memberships,
                revision.membership_sha256,
                policy,
                self.settings.configuration_encryption_key,
            )
        except (ValueError, KeyError, TypeError):
            raise conflict("managed_native_manifest_invalid") from None
        return expectation

    async def authenticated_installation(
        self, code: str, key: str, id: int
    ) -> ManagedInstallationModel:
        node = await self.nodes.authenticate(code, key)
        row = await self.installations.find(id)
        if row is None or row.node_id != node.id:
            raise NotFoundException(
                message="Managed installation not found.",
                message_code="managed_installation_missing",
                entity="managed_installation",
                identifier="id",
                identifier_value=id,
            )
        scope = None
        if row.state != "installed_closed":
            scope = await self.initial_scope(row.core_id)
        await self.nodes.locked(node.id)
        await self.nodes.authenticate(code, key)
        await self.states.lock_core(row.core_id)
        result = await self.installations.locked(id)
        if result.state != "installed_closed":
            if scope is None:
                raise conflict("managed_installation_scope_changed")
            await self.lock_scope(result.core_id, scope)
        return result

    @handle_conflicts
    @transactional
    async def issue(
        self, core_id: int, data: ManagedInstallationCreate
    ) -> ManagedInstallationModel:
        policy = self.policy()
        core = await self.cores.get(core_id)
        scope = await self.initial_scope(core_id)
        await self.nodes.locked(core.node_id)
        state = await self.states.locked(core_id)
        await self.lock_scope(core_id, scope)
        if (
            core.kind != "xray"
            or state.revision != data.expected_runtime_revision
        ):
            raise conflict("managed_runtime_revision_conflict")
        candidate = ManagedInstallationModel(
            node_id=core.node_id,
            core_id=core_id,
            runtime_revision_id=data.runtime_revision_id,
            installation_sha256="",
            encrypted_manifest="",
        )
        expectation = await self.current_expectation(candidate, policy)
        encrypted, digest = await asyncio.to_thread(
            ManagedInstallationEncoding.encode,
            expectation,
            self.settings.configuration_encryption_key,
        )
        existing = await self.installations.by_identity(
            core_id, data.runtime_revision_id, digest
        )
        if existing is not None:
            if existing.state not in {"issued", "leased", "installed_closed"}:
                raise conflict("managed_installation_legacy_unverified")
            return existing
        candidate.encrypted_manifest, candidate.installation_sha256 = (
            encrypted,
            digest,
        )
        result = await self.installations.create(candidate)
        return result

    @handle_conflicts
    @transactional
    async def claim(
        self, code: str, key: str, id: int
    ) -> ManagedInstallationClaim:
        policy = self.policy()
        row = await self.authenticated_installation(code, key, id)
        node = await self.nodes.get(row.node_id)
        now = datetime.now(UTC).replace(tzinfo=None)
        if (
            not node.is_enabled
            or row.state not in {"issued", "leased"}
            or (
                row.state == "leased"
                and row.claim_until is not None
                and row.claim_until > now
            )
        ):
            raise conflict("managed_installation_not_claimable")
        expectation = await self.current_expectation(row, policy)
        _, digest = await asyncio.to_thread(
            ManagedInstallationEncoding.encode,
            expectation,
            self.settings.configuration_encryption_key,
        )
        if digest != row.installation_sha256:
            raise conflict("managed_installation_policy_changed")
        revision = await self.revisions.get(
            row.runtime_revision_id, row.core_id
        )
        export = await asyncio.to_thread(
            RuntimePayload.decode,
            revision.encrypted_payload,
            self.settings.configuration_encryption_key,
        )
        token = secrets.token_urlsafe(32)
        token_hash = await asyncio.to_thread(RuntimePayload.digest, token)
        until = now + timedelta(seconds=policy.claim_seconds)
        await self.installations.change(
            row,
            ManagedInstallationModel.patch(
                state="leased", claim_hash=token_hash, claim_until=until
            ),
        )
        return ManagedInstallationClaim(
            installation_id=row.id,
            claim_token=token,
            claim_until=until.replace(tzinfo=UTC),
            expectation=expectation,
            artifact_content=export.artifacts[0].content,
        )

    @handle_conflicts
    @transactional
    async def acknowledge(
        self,
        code: str,
        key: str,
        id: int,
        data: ManagedClosedStartupAcknowledgement,
    ) -> ManagedInstalledClosedOut:
        row = await self.authenticated_installation(code, key, id)
        token_hash, acknowledgement_hash = await asyncio.gather(
            asyncio.to_thread(RuntimePayload.digest, data.claim_token),
            asyncio.to_thread(
                ManagedInstallationEncoding.acknowledgement_digest,
                data.claim_token,
                data.original_receipt,
                data.receipt,
            ),
        )
        if row.claim_hash is None or not compare_digest(
            row.claim_hash, token_hash
        ):
            raise conflict("managed_installation_lease_mismatch")
        existing = None
        if row.state == "installed_closed":
            existing = await self.epochs.by_epoch(data.receipt.epoch)
        if existing is not None:
            if (
                existing.installation_id != row.id
                or row.acknowledgement_sha256 != acknowledgement_hash
                or existing.receipt_sha256 != data.receipt.receipt_sha256
            ):
                raise conflict("managed_installation_ack_conflict")
            return ManagedInstalledClosedOut(
                installation_id=row.id,
                epoch_id=existing.id,
                process_epoch=existing.process_epoch,
                receipt_sha256=existing.receipt_sha256,
                observed_at=existing.installed_closed_at.replace(tzinfo=UTC),
            )
        policy = self.policy()
        now = datetime.now(UTC).replace(tzinfo=None)
        node = await self.nodes.get(row.node_id)
        if (
            not node.is_enabled
            or row.state != "leased"
            or row.claim_until is None
            or row.claim_until <= now
        ):
            raise conflict("managed_installation_lease_expired")
        expectation = await self.current_expectation(row, policy)
        _, digest = await asyncio.to_thread(
            ManagedInstallationEncoding.encode,
            expectation,
            self.settings.configuration_encryption_key,
        )
        if digest != row.installation_sha256:
            raise conflict("managed_installation_policy_changed")
        try:
            original = await asyncio.to_thread(
                ManagedWireEncoding.original_closed_startup,
                data.original_receipt,
                data.receipt,
                policy.capacity,
            )
        except ValueError:
            raise conflict("managed_closed_receipt_invalid") from None
        startup = original.startup
        observed = startup.observed_at.astimezone(UTC).replace(tzinfo=None)
        if (
            startup.installation != expectation.installation
            or startup.profiles != expectation.profiles
            or startup.adapter_revision != expectation.adapter_revision
            or startup.source_commit != expectation.source_commit
            or startup.enforcement_sha256 != expectation.enforcement_sha256
            or startup.window_policy_sha256 != expectation.window_policy_sha256
        ):
            raise conflict("managed_closed_installation_mismatch")
        if (
            observed > now + timedelta(seconds=policy.clock_skew_seconds)
            or observed + timedelta(seconds=policy.observation_seconds) < now
            or observed
            < row.claim_until
            - timedelta(
                seconds=policy.claim_seconds + policy.clock_skew_seconds
            )
        ):
            raise conflict("managed_closed_observation_stale")
        encrypted_receipt = await asyncio.to_thread(
            encrypt,
            data.original_receipt,
            self.settings.configuration_encryption_key,
        )
        epoch = await self.epochs.create(
            ManagedEpochModel(
                installation_id=row.id,
                process_epoch=startup.epoch,
                installed_closed_at=observed,
                receipt_sha256=data.receipt.receipt_sha256,
                encrypted_receipt=encrypted_receipt,
            )
        )
        await self.installations.change(
            row,
            ManagedInstallationModel.patch(
                state="installed_closed",
                acknowledgement_sha256=acknowledgement_hash,
            ),
        )
        return ManagedInstalledClosedOut(
            installation_id=row.id,
            epoch_id=epoch.id,
            process_epoch=epoch.process_epoch,
            receipt_sha256=epoch.receipt_sha256,
            observed_at=observed.replace(tzinfo=UTC),
        )

    @handle_conflicts
    @transactional
    async def rollover(
        self,
        code: str,
        key: str,
        previous_process_epoch: str,
        data: ManagedEpochRolloverSubmission,
    ) -> ManagedEpochRolloverOut:
        node = await self.nodes.authenticate(code, key)
        hint = await self.epoch_reader.epoch_hint(previous_process_epoch)
        if hint is None:
            raise conflict("managed_rollover_epoch_missing")
        initial = await self.installations.find(hint.installation_id)
        if initial is None or initial.node_id != node.id:
            raise conflict("managed_rollover_node_mismatch")
        policy = self.policy()
        runtime = self.settings.core_runtime
        seal_policy = policy.epoch_seal_policy
        if (
            runtime is None
            or seal_policy.mode != "strict"
            or seal_policy.limits is None
        ):
            raise conflict("managed_rollover_disabled")
        scope = await self.scopes.initial(
            initial.core_id, runtime.max_profiles + 1
        )
        if len(scope.profiles) > runtime.max_profiles:
            raise conflict("managed_runtime_snapshot_capacity")
        await self.customers.locked_many(
            sorted(
                {
                    customer_id
                    for owner in scope.owners
                    for customer_id in (
                        owner.customer_id,
                        owner.payer_customer_id or owner.customer_id,
                    )
                }
            )
        )
        await self.nodes.locked(node.id)
        node = await self.nodes.authenticate(code, key)
        state = await self.states.locked(initial.core_id)
        owners = await self.scopes.lock_subscriptions(
            [owner.subscription_id for owner in scope.owners]
        )
        configurations = await self.scopes.lock_configurations(
            initial.core_id, runtime.max_configurations + 1
        )
        profiles = await self.scopes.current_profiles(
            configurations, runtime.max_profiles + 1
        )
        installation = await self.installations.locked(initial.id)
        previous = await self.epochs.locked(hint.id)
        if (
            previous is None
            or previous.installation_id != installation.id
            or previous.process_epoch != previous_process_epoch
            or installation.node_id != node.id
            or installation.core_id != initial.core_id
            or installation.encrypted_manifest != initial.encrypted_manifest
        ):
            raise conflict("managed_rollover_scope_changed")
        request_digest, original_matches = await asyncio.gather(
            asyncio.to_thread(self.rollover_digest, data),
            asyncio.to_thread(self.rollover_original_matches, data),
        )
        existing = await self.epochs.rollover_from(previous.id)
        if existing is not None:
            if (
                not original_matches
                or existing.rollover_request_id != data.request_id
                or existing.rollover_request_sha256 != request_digest
                or existing.receipt_sha256 != data.receipt.receipt_sha256
            ):
                raise conflict("managed_rollover_request_reused")
            return self.rollover_output(previous, existing)
        if await self.epochs.rollover_by_request(data.request_id) is not None:
            raise conflict("managed_rollover_request_reused")
        if await self.epoch_seals.by_epoch(previous.id) is None:
            raise conflict("managed_rollover_finality_missing")
        if (
            owners != scope.owners
            or profiles != scope.profiles
            or len(configurations) > runtime.max_configurations
            or len(profiles) > runtime.max_profiles
            or installation.state != "installed_closed"
            or state is None
            or await self.commands.outstanding(initial.core_id) is not None
        ):
            raise conflict("managed_rollover_service_changed")
        expectation = await self.current_expectation(installation, policy)
        _, expected_digest = await asyncio.to_thread(
            ManagedInstallationEncoding.encode,
            expectation,
            self.settings.configuration_encryption_key,
        )
        if expected_digest != installation.installation_sha256:
            raise conflict("managed_rollover_policy_changed")
        try:
            original = await asyncio.to_thread(
                ManagedWireEncoding.original_closed_startup,
                data.original_receipt,
                data.receipt,
                policy.capacity,
            )
        except (ValueError, TypeError, KeyError):
            raise conflict("managed_rollover_receipt_invalid") from None
        startup = original.startup
        observed = startup.observed_at.astimezone(UTC).replace(tzinfo=None)
        now = datetime.now(UTC)
        if (
            startup.epoch == previous_process_epoch
            or startup.installation != expectation.installation
            or startup.profiles != expectation.profiles
            or startup.adapter_revision != expectation.adapter_revision
            or startup.source_commit != expectation.source_commit
            or startup.enforcement_sha256 != expectation.enforcement_sha256
            or startup.window_policy_sha256 != expectation.window_policy_sha256
            or observed
            > now.replace(tzinfo=None)
            + timedelta(seconds=policy.clock_skew_seconds)
            or observed + timedelta(seconds=policy.observation_seconds)
            < now.replace(tzinfo=None)
        ):
            raise conflict("managed_rollover_receipt_invalid")
        if await self.epochs.by_epoch(startup.epoch) is not None:
            raise conflict("managed_rollover_epoch_reused")
        epoch_count = await self.epochs.count_for_installation(
            installation.id, seal_policy.limits.max_epochs
        )
        if epoch_count.observed_count >= seal_policy.limits.max_epochs:
            raise conflict("managed_rollover_capacity")
        encrypted_receipt = await asyncio.to_thread(
            encrypt,
            data.original_receipt,
            self.settings.configuration_encryption_key,
        )
        current = await self.epochs.create(
            ManagedEpochModel(
                installation_id=installation.id,
                previous_epoch_id=previous.id,
                rollover_request_id=data.request_id,
                rollover_request_sha256=request_digest,
                process_epoch=startup.epoch,
                installed_closed_at=observed,
                receipt_sha256=data.receipt.receipt_sha256,
                encrypted_receipt=encrypted_receipt,
            )
        )
        return self.rollover_output(previous, current)
