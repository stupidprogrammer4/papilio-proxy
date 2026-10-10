"""Native leased CLOSED installation proof; never authorizes traffic."""

import asyncio
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
    IRuntimeRevisionService,
    IRuntimeStateService,
)
from src.modules.network.cores.interfaces import ICoreService
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
from src.modules.network.managed_runtime.domain.scopes import (
    ManagedInstallationScope,
)
from src.modules.network.managed_runtime.infra.scopes import (
    ManagedInstallationScopeReader,
)
from src.modules.network.managed_runtime.interfaces import (
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
        reader: RuntimeSnapshotReader,
        settings: PapilioSettings,
        scopes: ManagedInstallationScopeReader,
        customers: ICustomerService,
    ) -> None:
        self.installations, self.epochs = installations, epochs
        self.nodes, self.cores, self.states, self.revisions = (
            nodes,
            cores,
            states,
            revisions,
        )
        self.reader, self.settings = reader, settings
        self.scopes, self.customers = scopes, customers

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
        snapshot, _ = await asyncio.to_thread(
            RuntimePayload.fingerprints,
            facts,
            datetime.now(UTC).replace(tzinfo=None, microsecond=0),
        )
        if snapshot != revision.snapshot_sha256:
            raise conflict("managed_runtime_snapshot_stale")
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
