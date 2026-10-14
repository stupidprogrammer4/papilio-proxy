"""Native seal acceptance; no lease, refund, rollover or URL mutation."""

import asyncio
import secrets
from datetime import UTC, datetime

from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import encrypt

from src.config.settings import PapilioSettings
from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.network.core_runtime.interfaces import (
    IRuntimeCommandService,
    IRuntimeRevisionService,
    IRuntimeSnapshotQuery,
    IRuntimeStateService,
)
from src.modules.network.managed_runtime.app.admission_membership import (
    ManagedAdmissionMembership,
)
from src.modules.network.managed_runtime.app.epoch_seal_encoding import (
    ManagedEpochSealEncoding,
)
from src.modules.network.managed_runtime.app.installation_encoding import (
    ManagedInstallationEncoding,
)
from src.modules.network.managed_runtime.app.installations import conflict
from src.modules.network.managed_runtime.domain.epoch_seal_models import (
    ManagedEpochSealModel,
)
from src.modules.network.managed_runtime.domain.epoch_seals import (
    ManagedEpochSealOut,
    ManagedEpochSealSubmission,
)
from src.modules.network.managed_runtime.infra.epoch_seal_mysql import (
    ManagedEpochSealRepository,
)
from src.modules.network.managed_runtime.infra.epoch_seal_reads import (
    ManagedEpochSealReader,
)
from src.modules.network.managed_runtime.infra.scopes import (
    ManagedInstallationScopeReader,
)
from src.modules.network.managed_runtime.interfaces import (
    IManagedEpochService,
    IManagedInstallationService,
)
from src.modules.network.nodes.interfaces import INodeService


class ManagedEpochSealCommand:
    def __init__(
        self,
        seals: ManagedEpochSealRepository,
        reader: ManagedEpochSealReader,
        scopes: ManagedInstallationScopeReader,
        installations: IManagedInstallationService,
        epochs: IManagedEpochService,
        customers: ICustomerService,
        nodes: INodeService,
        states: IRuntimeStateService,
        revisions: IRuntimeRevisionService,
        commands: IRuntimeCommandService,
        snapshots: IRuntimeSnapshotQuery,
        settings: PapilioSettings,
    ) -> None:
        self.seals, self.reader, self.scopes = seals, reader, scopes
        self.installations, self.epochs = installations, epochs
        self.customers, self.nodes, self.states = customers, nodes, states
        self.revisions, self.commands, self.snapshots = (
            revisions,
            commands,
            snapshots,
        )
        self.settings = settings

    @staticmethod
    def output(
        row: ManagedEpochSealModel, epoch: str, installation_id: int
    ) -> ManagedEpochSealOut:
        return ManagedEpochSealOut(
            id=row.id,
            epoch=epoch,
            installation_id=installation_id,
            request_id=row.request_id,
            receipt_sha256=row.receipt_sha256,
            acceptance_id=row.acceptance_id,
            accepted_at=row.accepted_at.replace(tzinfo=UTC),
        )

    @handle_conflicts
    @transactional
    async def accept(
        self,
        code: str,
        key: str,
        process_epoch: str,
        data: ManagedEpochSealSubmission,
    ) -> ManagedEpochSealOut:
        node = await self.nodes.authenticate(code, key)
        hint = await self.reader.epoch_hint(process_epoch)
        if hint is None or data.receipt.epoch != process_epoch:
            raise conflict("managed_seal_epoch_missing")
        initial = await self.installations.find(hint.installation_id)
        if initial is None or initial.node_id != node.id:
            raise conflict("managed_seal_node_mismatch")
        installation_id, core_id, node_id = (
            initial.id,
            initial.core_id,
            node.id,
        )
        captured_manifest = initial.encrypted_manifest
        encryption_key = self.settings.configuration_encryption_key
        expectation = await asyncio.to_thread(
            ManagedInstallationEncoding.decode,
            captured_manifest,
            encryption_key,
        )
        runtime = self.settings.core_runtime
        profile_capacity = max(
            len(expectation.profiles), runtime.max_profiles if runtime else 0
        )
        scope = await self.scopes.initial(core_id, profile_capacity + 1)
        customer_ids = sorted(
            {
                id
                for owner in scope.owners
                for id in (
                    owner.customer_id,
                    owner.payer_customer_id or owner.customer_id,
                )
            }
        )
        await self.customers.locked_many(customer_ids)
        await self.nodes.locked(node_id)
        node = await self.nodes.authenticate(code, key)
        state = await self.states.locked(core_id)
        owners = await self.scopes.lock_subscriptions(
            sorted(owner.subscription_id for owner in scope.owners)
        )
        configurations = await self.scopes.lock_configurations(
            core_id,
            max(
                len(expectation.profiles),
                runtime.max_configurations if runtime else 0,
            )
            + 1,
        )
        profiles = await self.scopes.current_profiles(
            configurations, profile_capacity + 1
        )
        installation = await self.installations.locked(installation_id)
        epoch = await self.epochs.locked(hint.id)
        if (
            epoch is None
            or epoch.installation_id != installation_id
            or epoch.process_epoch != process_epoch
            or installation.node_id != node.id
            or installation.core_id != core_id
            or installation.encrypted_manifest != captured_manifest
        ):
            raise conflict("managed_seal_scope_changed")
        digest, original_matches = await asyncio.gather(
            asyncio.to_thread(ManagedEpochSealEncoding.request_digest, data),
            asyncio.to_thread(ManagedEpochSealEncoding.original_matches, data),
        )
        existing = await self.seals.by_epoch(epoch.id)
        if existing is not None:
            if (
                not original_matches
                or existing.request_id != data.receipt.request_id
                or existing.request_sha256 != digest
                or existing.receipt_sha256 != data.receipt.receipt_sha256
            ):
                raise conflict("managed_seal_request_reused")
            return self.output(existing, process_epoch, installation_id)
        policy = self.settings.managed_adapter
        seal_policy = policy.epoch_seal_policy if policy is not None else None
        if (
            policy is None
            or not policy.enabled
            or seal_policy is None
            or seal_policy.mode != "strict"
            or seal_policy.limits is None
        ):
            raise conflict("managed_seal_disabled")
        if runtime is None or not runtime.enabled:
            raise conflict("managed_seal_runtime_disabled")
        if (
            owners != scope.owners
            or profiles != scope.profiles
            or len(profiles) > runtime.max_profiles
            or len(configurations) > runtime.max_configurations
            or tuple(row.profile_id for row in profiles)
            != tuple(row.binding.profile_id for row in expectation.profiles)
            or installation.state != "installed_closed"
            or state is None
            or expectation.runtime_state_revision != state.revision
            or expectation.runtime_revision_id
            != installation.runtime_revision_id
            or expectation.adapter_revision != policy.adapter_revision
            or expectation.source_commit != policy.source_commit
            or expectation.installation.executable_sha256
            != policy.executable_sha256
            or expectation.installation.materials_sha256
            != policy.materials_sha256
            or expectation.enforcement_sha256 != policy.enforcement_sha256
            or expectation.window_policy_sha256 != policy.window_policy_sha256
            or expectation.capacity != policy.capacity
            or expectation.claim_seconds != policy.claim_seconds
            or expectation.observation_seconds != policy.observation_seconds
            or expectation.clock_skew_seconds != policy.clock_skew_seconds
        ):
            raise conflict("managed_seal_membership_or_policy_changed")
        if await self.commands.outstanding(core_id) is not None:
            raise conflict("managed_seal_runtime_pending")
        revision = await self.revisions.get(
            installation.runtime_revision_id, core_id
        )
        if (
            revision.encrypted_memberships is None
            or revision.membership_sha256 is None
        ):
            raise conflict("managed_seal_membership_missing")
        facts = await self.snapshots.facts(
            core_id, runtime.max_configurations + 1, runtime.max_profiles + 1
        )
        now = datetime.now(UTC)
        try:
            await asyncio.to_thread(
                ManagedAdmissionMembership.verify,
                facts,
                revision.encrypted_memberships,
                revision.membership_sha256,
                revision.snapshot_sha256,
                now.replace(tzinfo=None),
                encryption_key,
            )
            native = await self.reader.locked_epoch(
                epoch.id,
                process_epoch,
                node.id,
                seal_policy.limits.max_windows_per_epoch + 1,
            )
            await asyncio.to_thread(
                ManagedEpochSealEncoding.verify,
                data,
                expectation,
                epoch.receipt_sha256,
                process_epoch,
                native,
                seal_policy.limits,
                now,
                epoch.installed_closed_at,
                encryption_key,
            )
        except (ValueError, TypeError, KeyError):
            raise conflict("managed_seal_receipt_invalid") from None
        encrypted = await asyncio.to_thread(
            encrypt, data.original_receipt, encryption_key
        )
        stored = await self.seals.create(
            ManagedEpochSealModel(
                epoch_id=epoch.id,
                request_id=data.receipt.request_id,
                request_sha256=digest,
                receipt_sha256=data.receipt.receipt_sha256,
                acceptance_id=secrets.token_hex(16),
                accepted_at=now.replace(tzinfo=None),
                encrypted_receipt=encrypted,
            )
        )
        return self.output(stored, process_epoch, installation_id)
