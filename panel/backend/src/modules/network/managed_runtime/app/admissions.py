"""Atomic strict admission acceptance and paid provisioning transition."""

import asyncio
from datetime import UTC, datetime, timedelta

from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import encrypt, hash_sha256, secure_compare

from src.config.settings import PapilioSettings
from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.network.configurations.infra.mysql import (
    ConfigurationRepository,
)
from src.modules.network.core_runtime.infra.readers import (
    RuntimeSnapshotReader,
)
from src.modules.network.core_runtime.interfaces import (
    IRuntimeRevisionService,
    IRuntimeStateService,
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
    ManagedAdmissionOut,
    ManagedAdmissionSubmission,
)
from src.modules.network.managed_runtime.domain.models import (
    ManagedAdmissionModel,
    ManagedWindowModel,
)
from src.modules.network.managed_runtime.infra.scopes import (
    ManagedInstallationScopeReader,
)
from src.modules.network.managed_runtime.interfaces import (
    IManagedAdmissionService,
    IManagedEpochService,
    IManagedInstallationService,
    IManagedWindowService,
)
from src.modules.network.nodes.interfaces import INodeService
from src.modules.network.provisioning.domain.managed import (
    ManagedApplicationEvidence,
)
from src.modules.network.provisioning.interfaces import IProvisioningCommand
from src.modules.network.usage.infra.mysql import UsageGrantRepository
from src.modules.sales.subscriptions.infra.mysql import SubscriptionRepository


class ManagedAdmissionCommand:
    def __init__(
        self,
        admissions: IManagedAdmissionService,
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
        grants: UsageGrantRepository,
        configurations: ConfigurationRepository,
        provisioning: IProvisioningCommand,
        settings: PapilioSettings,
    ) -> None:
        self.admissions, self.windows, self.epochs = (
            admissions,
            windows,
            epochs,
        )
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
            observed_at=admission.observed_at,
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
