"""Atomic strict admission acceptance and paid provisioning transition."""

import asyncio
from datetime import UTC, datetime, timedelta

import anyio
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import encrypt, hash_sha256, secure_compare

from src.config.settings import PapilioSettings
from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.network.configurations.infra.mysql import (
    ConfigurationRepository,
)
from src.modules.network.configurations.interfaces import IConfigurationCommand
from src.modules.network.core_runtime.infra.readers import (
    RuntimeSnapshotReader,
)
from src.modules.network.core_runtime.interfaces import (
    IRuntimeRevisionService,
    IRuntimeSnapshotQuery,
    IRuntimeStateService,
)
from src.modules.network.managed_runtime.app.admission_computation import (
    compute_managed_admission_batch_digest,
    prepare_managed_admission_batch,
)
from src.modules.network.managed_runtime.app.admission_encoding import (
    ManagedAdmissionEncoding,
)
from src.modules.network.managed_runtime.app.admission_membership import (
    ManagedAdmissionMembership,
)
from src.modules.network.managed_runtime.app.installation_encoding import (
    ManagedInstallationEncoding,
)
from src.modules.network.managed_runtime.app.installations import conflict
from src.modules.network.managed_runtime.app.window_encoding import (
    ManagedWindowEncoding,
)
from src.modules.network.managed_runtime.domain.admissions import (
    ManagedAdmissionBatchCreate,
    ManagedAdmissionBatchItemOut,
    ManagedAdmissionBatchOut,
    ManagedAdmissionOut,
    ManagedAdmissionSubmission,
)
from src.modules.network.managed_runtime.domain.models import (
    ManagedAdmissionModel,
    ManagedOperationBatchModel,
    ManagedWindowModel,
)
from src.modules.network.managed_runtime.domain.results import (
    ManagedAdmissionBatchDigest,
)
from src.modules.network.managed_runtime.infra.scopes import (
    ManagedInstallationScopeReader,
)
from src.modules.network.managed_runtime.interfaces import (
    IManagedAdmissionService,
    IManagedEpochService,
    IManagedInstallationService,
    IManagedOperationBatchService,
    IManagedWindowService,
)
from src.modules.network.nodes.interfaces import INodeService
from src.modules.network.provisioning.domain.managed import (
    ManagedApplicationBatch,
    ManagedApplicationBatchItem,
    ManagedApplicationEvidence,
)
from src.modules.network.provisioning.interfaces import IProvisioningCommand
from src.modules.network.usage.infra.mysql import UsageGrantRepository
from src.modules.network.usage.interfaces import IUsageGrantService
from src.modules.sales.subscriptions.infra.mysql import SubscriptionRepository
from src.modules.sales.subscriptions.interfaces import (
    ISubscriptionBatchService,
)


def _utc_timestamp(timestamp: datetime) -> datetime:
    """Serialize persisted UTC timestamps with an explicit UTC offset."""
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


class ManagedAdmissionCommand:
    def __init__(
        self,
        admissions: IManagedAdmissionService,
        operation_batches: IManagedOperationBatchService,
        windows: IManagedWindowService,
        epochs: IManagedEpochService,
        installations: IManagedInstallationService,
        nodes: INodeService,
        states: IRuntimeStateService,
        revisions: IRuntimeRevisionService,
        snapshots: RuntimeSnapshotReader,
        scopes: ManagedInstallationScopeReader,
        customers: ICustomerService,
        subscriptions: SubscriptionRepository,
        subscription_batches: ISubscriptionBatchService,
        grants: UsageGrantRepository,
        grant_service: IUsageGrantService,
        configurations: ConfigurationRepository,
        configuration_commands: IConfigurationCommand,
        snapshot_query: IRuntimeSnapshotQuery,
        provisioning: IProvisioningCommand,
        settings: PapilioSettings,
    ) -> None:
        self.admissions, self.windows, self.epochs = (
            admissions,
            windows,
            epochs,
        )
        self.operation_batches = operation_batches
        self.installations, self.nodes, self.states = (
            installations,
            nodes,
            states,
        )
        self.customers, self.subscriptions, self.grants = (
            customers,
            subscriptions,
            grants,
        )
        self.subscription_batches = subscription_batches
        self.grant_service = grant_service
        self.configuration_commands = configuration_commands
        self.snapshot_query = snapshot_query
        self.configurations, self.provisioning, self.settings = (
            configurations,
            provisioning,
            settings,
        )
        self.revisions, self.snapshots, self.scopes = (
            revisions,
            snapshots,
            scopes,
        )

    @handle_conflicts
    @transactional
    async def acknowledge(
        self,
        code: str,
        key: str,
        window_id: str,
        data: ManagedAdmissionSubmission,
    ) -> ManagedAdmissionOut:
        node = await self.nodes.authenticate(code, key)
        hint = await self.windows.by_identity(window_id)
        if hint is None or hint.provision_task_id is None:
            raise conflict("managed_paid_window_missing")
        epoch = await self.epochs.find(hint.epoch_id)
        if epoch is None:
            raise conflict("managed_window_epoch_missing")
        initial = await self.installations.find(epoch.installation_id)
        subscription_hint = await self.subscriptions.get_by_id(
            hint.subscription_id
        )
        if (
            initial is None
            or initial.node_id != node.id
            or subscription_hint is None
        ):
            raise conflict("managed_window_node_mismatch")
        customer_id = subscription_hint.customer_id
        payer_id = subscription_hint.payer_customer_id
        runtime = self.settings.core_runtime
        scope = None
        scope_capacity_exceeded = False
        scope_changed = False
        customer_ids = {customer_id, payer_id or customer_id}
        if runtime is not None:
            scope = await self.scopes.initial(
                initial.core_id, runtime.max_profiles + 1
            )
            scope_capacity_exceeded = (
                len(scope.profiles) > runtime.max_profiles
            )
            customer_ids.update(
                owner_id
                for owner in scope.owners
                for owner_id in (
                    owner.customer_id,
                    owner.payer_customer_id or owner.customer_id,
                )
            )
        await self.customers.locked_many(
            sorted(customer_ids | {customer_id, payer_id or customer_id})
        )
        await self.nodes.locked(node.id)
        node = await self.nodes.authenticate(code, key)
        state = await self.states.locked(initial.core_id)
        if scope is not None and runtime is not None:
            owners = await self.scopes.lock_subscriptions(
                [owner.subscription_id for owner in scope.owners]
            )
            scope_changed = owners != scope.owners
            configurations = await self.scopes.lock_configurations(
                initial.core_id, runtime.max_configurations + 1
            )
            scope_capacity_exceeded = (
                scope_capacity_exceeded
                or len(configurations) > runtime.max_configurations
            )
            profiles = await self.scopes.current_profiles(
                configurations, runtime.max_profiles + 1
            )
            scope_changed = scope_changed or profiles != scope.profiles
        subscription = await self.subscriptions.locked(hint.subscription_id)
        if (
            subscription is None
            or subscription.customer_id != customer_id
            or subscription.payer_customer_id != payer_id
        ):
            raise conflict("provision_subscription_owner_changed")
        installation = await self.installations.locked(initial.id)
        window = await self.windows.locked(hint.id)
        if (
            window is None
            or window.provision_task_id is None
            or not window.encrypted_provision_claim
        ):
            raise conflict("managed_paid_claim_missing")
        detached = ManagedWindowModel.model_validate(window.model_dump())
        expectation = await asyncio.to_thread(
            ManagedInstallationEncoding.decode,
            installation.encrypted_manifest,
            self.settings.configuration_encryption_key,
        )
        try:
            admission = await asyncio.to_thread(
                ManagedAdmissionEncoding.verify,
                data,
                detached,
                expectation,
                epoch.receipt_sha256,
                self.settings.configuration_encryption_key,
            )
            original = await asyncio.to_thread(
                ManagedWindowEncoding.output,
                detached,
                self.settings.configuration_encryption_key,
            )
        except (ValueError, TypeError, KeyError):
            raise conflict("managed_admission_receipt_invalid") from None
        claim = original.provision_claim
        if (
            claim is None
            or claim.task_id != window.provision_task_id
            or not secure_compare(claim.claim_token, data.claim_token)
        ):
            raise conflict("managed_provision_claim_invalid")
        existing = await self.admissions.by_window(window.id)
        result = ManagedAdmissionOut(
            window_id=window.window_id,
            provision_task_id=window.provision_task_id,
            admission_sha256=data.receipt.receipt_sha256,
            observed_at=_utc_timestamp(admission.observed_at).replace(
                microsecond=0
            ),
        )
        if existing is not None:
            if (
                existing.receipt_sha256 != data.receipt.receipt_sha256
                or existing.outcome != "applied"
            ):
                raise conflict("managed_admission_receipt_reused")
            return result
        if scope_capacity_exceeded:
            raise conflict("managed_runtime_snapshot_capacity")
        if scope_changed:
            raise conflict("managed_installation_scope_changed")
        now = datetime.now(UTC).replace(tzinfo=None)
        observed = admission.observed_at.astimezone(UTC).replace(tzinfo=None)
        policy = self.settings.managed_adapter
        runtime = self.settings.core_runtime
        if (
            policy is None
            or not policy.enabled
            or policy.paid_mode != "strict_admission"
            or policy.window_mode != "reserved"
            or runtime is None
            or not runtime.enabled
            or not runtime.allow_start
            or state.automation_paused
            or state.revision != expectation.runtime_state_revision
            or not node.is_enabled
            or installation.state != "installed_closed"
            or window.valid_until <= now
            or claim.claim_until.replace(tzinfo=None) <= now
            or observed
            > now + timedelta(seconds=expectation.clock_skew_seconds)
            or now - observed
            > timedelta(seconds=expectation.observation_seconds)
        ):
            raise conflict("managed_admission_observation_expired")
        grant = await self.grants.locked(window.grant_id)
        if grant is None or grant.is_closed:
            raise conflict("managed_admission_window_closed")
        configuration = await self.configurations.locked(
            admission.window.binding.configuration_id
        )
        if (
            configuration is None
            or configuration.core_id != installation.core_id
            or configuration.node_id != node.id
            or configuration.revision
            != admission.window.binding.configuration_revision
        ):
            raise conflict("managed_admission_configuration_changed")
        revision = await self.revisions.get(
            installation.runtime_revision_id, installation.core_id
        )
        if (
            revision.encrypted_memberships is None
            or revision.membership_sha256 is None
        ):
            raise conflict("managed_runtime_snapshot_stale")
        snapshot = await self.snapshots.facts(
            initial.core_id,
            runtime.max_configurations + 1,
            runtime.max_profiles + 1,
        )
        try:
            await asyncio.to_thread(
                ManagedAdmissionMembership.verify,
                snapshot,
                revision.encrypted_memberships,
                revision.membership_sha256,
                revision.snapshot_sha256,
                now,
                self.settings.configuration_encryption_key,
            )
        except (ValueError, TypeError, KeyError):
            raise conflict("managed_runtime_snapshot_stale") from None
        encrypted = await asyncio.to_thread(
            encrypt,
            data.original_receipt,
            self.settings.configuration_encryption_key,
        )
        await self.admissions.create(
            ManagedAdmissionModel(
                window_id=window.id,
                provision_task_id=window.provision_task_id,
                receipt_sha256=data.receipt.receipt_sha256,
                outcome="applied",
                observed_at=observed,
                encrypted_receipt=encrypted,
            )
        )
        claim_hash = await asyncio.to_thread(hash_sha256, claim.claim_token)
        await self.provisioning.apply_managed(
            window.provision_task_id,
            ManagedApplicationEvidence(
                subscription_id=subscription.id,
                node_id=node.id,
                core_id=installation.core_id,
                profile_id=window.profile_id,
                generation=window.generation,
                configuration_id=configuration.id,
                configuration_revision=configuration.revision,
                installed_revision_id=installation.runtime_revision_id,
                membership_sha256=admission.window.membership_sha256,
                claim_hash=claim_hash,
                admission_sha256=data.receipt.receipt_sha256,
                observed_at=observed,
            ),
        )
        return result

    @handle_conflicts
    @transactional
    async def acknowledge_many(
        self,
        code: str,
        key: str,
        data: ManagedAdmissionBatchCreate,
    ) -> ManagedAdmissionBatchOut:
        policy = self.settings.managed_adapter
        runtime = self.settings.core_runtime
        if (
            policy is None
            or runtime is None
            or not policy.enabled
            or policy.paid_mode != "strict_admission"
            or policy.window_mode != "reserved"
            or not runtime.enabled
            or not runtime.allow_start
            or len(data.windows) > runtime.max_profiles
            or len(data.windows) > policy.capacity.max_profiles_per_barrier
        ):
            raise conflict("managed_admission_batch_capacity_or_policy")
        node = await self.nodes.authenticate(code, key)
        window_ids = [item.window_id for item in data.windows]
        hints = await self.windows.find_by_identities_many(window_ids)
        windows_by_id = {row.window_id: row for row in hints}
        if set(windows_by_id) != set(window_ids):
            raise conflict("managed_paid_window_missing")
        epoch_ids = {row.epoch_id for row in hints}
        profile_ids = {row.profile_id for row in hints}
        if len(epoch_ids) != 1 or len(profile_ids) != len(hints):
            raise conflict("managed_admission_batch_scope_mismatch")
        epoch_hint = await self.epochs.find(next(iter(epoch_ids)))
        if epoch_hint is None:
            raise conflict("managed_window_epoch_missing")
        installation_hint = await self.installations.find(
            epoch_hint.installation_id
        )
        if (
            installation_hint is None
            or installation_hint.node_id != node.id
            or any(
                row.provision_task_id is None or row.subscription_id <= 0
                for row in hints
            )
        ):
            raise conflict("managed_window_node_mismatch")
        digest = await compute_managed_admission_batch_digest(
            installation_hint.id, data
        )
        previous = await self.operation_batches.by_identity(
            installation_hint.id,
            "admission",
            data.batch_request_key,
        )
        if previous is not None:
            return await self._replay_admission_batch(
                previous, digest, data, hints
            )
        subscription_ids = sorted({row.subscription_id for row in hints})
        subscription_hints = await self.subscription_batches.by_ids_many(
            subscription_ids
        )
        subscriptions_by_id = {row.id: row for row in subscription_hints}
        if set(subscriptions_by_id) != set(subscription_ids):
            raise conflict("managed_paid_window_missing")
        scope = await self.scopes.initial(
            installation_hint.core_id, runtime.max_profiles + 1
        )
        customer_ids = {
            owner_id
            for subscription in subscription_hints
            for owner_id in (
                subscription.customer_id,
                subscription.payer_customer_id or subscription.customer_id,
            )
        }
        customer_ids.update(
            owner_id
            for owner in scope.owners
            for owner_id in (
                owner.customer_id,
                owner.payer_customer_id or owner.customer_id,
            )
        )
        await self.customers.locked_many(sorted(customer_ids))
        await self.nodes.locked(node.id)
        node = await self.nodes.authenticate(code, key)
        state = await self.states.locked(installation_hint.core_id)
        owners = await self.scopes.lock_subscriptions(
            [owner.subscription_id for owner in scope.owners]
        )
        scope_changed = owners != scope.owners
        scoped_configurations = await self.scopes.lock_configurations(
            installation_hint.core_id, runtime.max_configurations + 1
        )
        scope_capacity_exceeded = (
            len(scope.profiles) > runtime.max_profiles
            or len(scoped_configurations) > runtime.max_configurations
        )
        current_profiles = await self.scopes.current_profiles(
            scoped_configurations, runtime.max_profiles + 1
        )
        scope_changed = scope_changed or current_profiles != scope.profiles
        subscriptions = await self.subscription_batches.locked_many(
            subscription_ids
        )
        subscriptions_by_id = {row.id: row for row in subscriptions}
        installation = await self.installations.locked(installation_hint.id)
        epoch = await self.epochs.locked(epoch_hint.id)
        windows = await self.windows.by_identities_many(window_ids)
        windows_by_id = {row.window_id: row for row in windows}
        expectation = await anyio.to_thread.run_sync(
            ManagedInstallationEncoding.decode,
            installation.encrypted_manifest,
            self.settings.configuration_encryption_key,
        )
        if (
            node.id != installation_hint.node_id
            or installation.node_id != node.id
            or installation.core_id != installation_hint.core_id
            or epoch is None
            or epoch.installation_id != installation.id
            or epoch.process_epoch != epoch_hint.process_epoch
            or len(windows_by_id) != len(window_ids)
            or set(subscriptions_by_id) != set(subscription_ids)
            or state.revision != expectation.runtime_state_revision
        ):
            raise conflict("managed_admission_batch_scope_changed")
        locked_batch = await self.operation_batches.by_identity(
            installation.id, "admission", data.batch_request_key
        )
        if locked_batch is not None:
            return await self._replay_admission_batch(
                locked_batch, digest, data, windows
            )
        existing = await self.admissions.by_windows_many(
            [row.id for row in windows]
        )
        if existing:
            raise conflict("managed_admission_batch_incomplete")
        if (
            state.automation_paused
            or not node.is_enabled
            or installation.state != "installed_closed"
            or scope_capacity_exceeded
            or scope_changed
        ):
            raise conflict("managed_admission_runtime_unavailable")
        detached_windows = tuple(
            ManagedWindowModel.model_validate(row.model_dump())
            for row in windows
        )
        original_rows = await anyio.to_thread.run_sync(
            ManagedWindowEncoding.outputs,
            detached_windows,
            self.settings.configuration_encryption_key,
        )
        window_by_id = {row.window_id: row for row in windows}
        originals_by_id = {row.window.window_id: row for row in original_rows}
        configuration_ids = sorted(
            {item.window.binding.configuration_id for item in original_rows}
        )
        configurations = await self.configuration_commands.locked_many(
            configuration_ids
        )
        configurations_by_id = {row.id: row for row in configurations}
        grant_ids = [row.grant_id for row in windows]
        grants = await self.grant_service.locked_many(grant_ids)
        grants_by_id = {row.id: row for row in grants}
        if len(configurations_by_id) != len(configuration_ids) or len(
            grants_by_id
        ) != len(windows):
            raise conflict("managed_admission_configuration_changed")
        request_by_window = {item.window_id: item for item in data.windows}
        now_aware = datetime.now(UTC)
        now = now_aware.replace(tzinfo=None, microsecond=0)
        for window in windows:
            original = originals_by_id[window.window_id]
            claim = original.provision_claim
            configuration = configurations_by_id[
                original.window.binding.configuration_id
            ]
            subscription = subscriptions_by_id[window.subscription_id]
            grant = grants_by_id[window.grant_id]
            submitted = request_by_window[window.window_id].submission
            if (
                grant.is_closed
                or grant.node_id != node.id
                or grant.subscription_id != window.subscription_id
                or grant.profile_id != window.profile_id
                or grant.generation != window.generation
                or grant.configuration_revision
                != original.window.binding.configuration_revision
                or grant.process_epoch != epoch.process_epoch
                or grant.allocated_bytes != window.allocated_bytes
                or grant.valid_until <= now
                or abs(grant.valid_until - window.valid_until)
                >= timedelta(seconds=1)
                or window.provision_task_id is None
                or claim is None
                or claim.task_id != window.provision_task_id
                or not secure_compare(claim.claim_token, submitted.claim_token)
                or window.epoch_id != epoch.id
                or window.generation != subscription.renewal_count
                or subscription.status not in {"pending_provision", "active"}
                or configuration.core_id != installation.core_id
                or configuration.node_id != node.id
                or configuration.revision
                != original.window.binding.configuration_revision
                or window.valid_until <= now
                or claim.claim_until <= now_aware
            ):
                raise conflict("managed_admission_observation_expired")
        revision = await self.revisions.get(
            installation.runtime_revision_id, installation.core_id
        )
        snapshot = await self.snapshot_query.facts(
            installation.core_id,
            runtime.max_configurations + 1,
            runtime.max_profiles + 1,
        )
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        try:
            prepared = await prepare_managed_admission_batch(
                data,
                detached_windows,
                expectation,
                epoch.receipt_sha256,
                revision,
                snapshot,
                now,
                self.settings.configuration_encryption_key,
            )
        except (ValueError, TypeError, KeyError):
            raise conflict("managed_runtime_snapshot_stale") from None
        if any(
            item.admission.observed_at
            > now_aware + timedelta(seconds=expectation.clock_skew_seconds)
            or now_aware - item.admission.observed_at
            > timedelta(seconds=expectation.observation_seconds)
            for item in prepared
        ):
            raise conflict("managed_admission_observation_expired")
        receipt_sha256_by_window = {
            item.window_id: item.submission.receipt.receipt_sha256
            for item in data.windows
        }
        task_id_by_window = {
            window.window_id: self._provision_task_id(window)
            for window in windows
        }
        admissions = [
            ManagedAdmissionModel(
                window_id=window_by_id[item.window_id].id,
                provision_task_id=task_id_by_window[item.window_id],
                receipt_sha256=receipt_sha256_by_window[item.window_id],
                outcome="applied",
                observed_at=item.admission.observed_at.astimezone(UTC)
                .replace(tzinfo=None)
                .replace(microsecond=0),
                encrypted_receipt=item.encrypted_receipt,
            )
            for item in prepared
        ]
        await self.operation_batches.create(
            ManagedOperationBatchModel(
                installation_id=installation.id,
                epoch_id=epoch.id,
                operation="admission",
                request_key=data.batch_request_key,
                request_sha256=digest.request_sha256,
                item_count=len(data.windows),
                accepted_at=now,
            )
        )
        await self.admissions.create_many(admissions)
        evidence = ManagedApplicationBatch(
            items=tuple(
                ManagedApplicationBatchItem(
                    task_id=task_id_by_window[item.window_id],
                    evidence=ManagedApplicationEvidence(
                        subscription_id=window_by_id[
                            item.window_id
                        ].subscription_id,
                        node_id=node.id,
                        core_id=installation.core_id,
                        profile_id=window_by_id[item.window_id].profile_id,
                        generation=window_by_id[item.window_id].generation,
                        configuration_id=item.admission.window.binding.configuration_id,
                        configuration_revision=item.admission.window.binding.configuration_revision,
                        installed_revision_id=installation.runtime_revision_id,
                        membership_sha256=item.admission.window.membership_sha256,
                        claim_hash=item.claim_hash,
                        admission_sha256=receipt_sha256_by_window[
                            item.window_id
                        ],
                        observed_at=item.admission.observed_at,
                    ),
                )
                for item in prepared
            )
        )
        await self.provisioning.apply_managed_many(evidence)
        return self._admission_batch_output(data, windows, admissions)

    async def _replay_admission_batch(
        self,
        batch: ManagedOperationBatchModel,
        digest: ManagedAdmissionBatchDigest,
        data: ManagedAdmissionBatchCreate,
        windows: list[ManagedWindowModel],
    ) -> ManagedAdmissionBatchOut:
        if (
            batch.operation != "admission"
            or batch.request_sha256 != digest.request_sha256
            or batch.item_count != len(data.windows)
        ):
            raise conflict("managed_admission_batch_reused")
        window_by_id = {row.window_id: row for row in windows}
        admissions = await self.admissions.by_windows_many(
            [row.id for row in windows]
        )
        if len(admissions) != batch.item_count:
            raise conflict("managed_admission_batch_incomplete")
        admission_by_window = {row.window_id: row for row in admissions}
        for item in data.windows:
            window = window_by_id[item.window_id]
            admission = admission_by_window.get(window.id)
            if (
                admission is None
                or admission.provision_task_id != window.provision_task_id
                or admission.receipt_sha256
                != item.submission.receipt.receipt_sha256
                or admission.outcome != "applied"
            ):
                raise conflict("managed_admission_batch_incomplete")
        return self._admission_batch_output(data, windows, admissions)

    @staticmethod
    def _admission_batch_output(
        data: ManagedAdmissionBatchCreate,
        windows: list[ManagedWindowModel],
        admissions: list[ManagedAdmissionModel],
    ) -> ManagedAdmissionBatchOut:
        windows_by_id = {row.window_id: row for row in windows}
        admissions_by_window = {row.window_id: row for row in admissions}
        results = [
            ManagedAdmissionBatchItemOut(
                window_id=item.window_id,
                result=ManagedAdmissionOut(
                    window_id=item.window_id,
                    provision_task_id=ManagedAdmissionCommand._provision_task_id(
                        windows_by_id[item.window_id]
                    ),
                    admission_sha256=admissions_by_window[
                        windows_by_id[item.window_id].id
                    ].receipt_sha256,
                    observed_at=_utc_timestamp(
                        admissions_by_window[
                            windows_by_id[item.window_id].id
                        ].observed_at
                    ),
                ),
            )
            for item in data.windows
        ]
        return ManagedAdmissionBatchOut(
            batch_request_key=data.batch_request_key,
            windows=results,
        )

    @staticmethod
    def _provision_task_id(window: ManagedWindowModel) -> int:
        if window.provision_task_id is None:
            raise conflict("managed_paid_claim_missing")
        task_id = window.provision_task_id
        return task_id
