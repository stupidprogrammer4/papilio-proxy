"""Initial quota reservations and optional immutable paid task leases."""

import asyncio
import secrets
from datetime import UTC, datetime, timedelta

from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import encrypt, hash_sha256

from src.config.settings import PapilioSettings
from src.modules.accounts.customers.app.policies import CustomerAccessPolicy
from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.network.core_runtime.app.commands import conflict
from src.modules.network.core_runtime.infra.readers import (
    RuntimeSnapshotReader,
)
from src.modules.network.core_runtime.interfaces import (
    IRuntimeCommandService,
    IRuntimeRevisionService,
    IRuntimeStateService,
)
from src.modules.network.managed_runtime.app.admission_membership import (
    ManagedAdmissionMembership,
)
from src.modules.network.managed_runtime.app.installation_encoding import (
    ManagedInstallationEncoding,
)
from src.modules.network.managed_runtime.app.window_encoding import (
    ManagedWindowEncoding,
)
from src.modules.network.managed_runtime.domain.models import (
    ManagedWindowModel,
)
from src.modules.network.managed_runtime.domain.windows import (
    ManagedInitialWindowCreate,
    ManagedInitialWindowOut,
    ManagedProvisionClaim,
)
from src.modules.network.managed_runtime.domain.wire import ManagedWindowWire
from src.modules.network.managed_runtime.infra.scopes import (
    ManagedInstallationScopeReader,
)
from src.modules.network.managed_runtime.interfaces import (
    IManagedEpochSealService,
    IManagedEpochService,
    IManagedInstallationService,
    IManagedWindowService,
)
from src.modules.network.nodes.interfaces import INodeService
from src.modules.network.provisioning.domain.models import ProvisionTaskModel
from src.modules.network.provisioning.infra.mysql import (
    ProvisionRequestRepository,
    ProvisionTaskRepository,
)
from src.modules.network.usage.domain.models import UsageGrantModel
from src.modules.network.usage.interfaces import (
    IUsageFactsReader,
    IUsageGrantService,
)
from src.modules.sales.catalog.domain.policies import (
    FulfillmentPolicy,
    QuotaPolicy,
)
from src.modules.sales.subscriptions.infra.mysql import SubscriptionRepository


class ManagedInitialWindowCommand:
    def __init__(
        self,
        installations: IManagedInstallationService,
        epochs: IManagedEpochService,
        windows: IManagedWindowService,
        scopes: ManagedInstallationScopeReader,
        epoch_seals: IManagedEpochSealService,
        customers: ICustomerService,
        nodes: INodeService,
        states: IRuntimeStateService,
        revisions: IRuntimeRevisionService,
        commands: IRuntimeCommandService,
        snapshots: RuntimeSnapshotReader,
        grants: IUsageGrantService,
        subscriptions: SubscriptionRepository,
        facts: IUsageFactsReader,
        tasks: ProvisionTaskRepository,
        requests: ProvisionRequestRepository,
        settings: PapilioSettings,
    ) -> None:
        self.installations, self.epochs, self.windows = (
            installations,
            epochs,
            windows,
        )
        self.scopes, self.epoch_seals = scopes, epoch_seals
        self.customers, self.nodes = customers, nodes
        self.states, self.revisions, self.commands = (
            states,
            revisions,
            commands,
        )
        self.snapshots, self.grants = snapshots, grants
        self.tasks, self.requests = tasks, requests
        self.subscriptions, self.facts, self.settings = (
            subscriptions,
            facts,
            settings,
        )

    @handle_conflicts
    @transactional
    async def issue(
        self, code: str, key: str, id: int, data: ManagedInitialWindowCreate
    ) -> ManagedInitialWindowOut:
        policy = self.settings.managed_adapter
        runtime = self.settings.core_runtime
        if (
            policy is None
            or not policy.enabled
            or policy.window_mode != "reserved"
        ):
            raise conflict("managed_window_disabled")
        if runtime is None or not runtime.enabled or not runtime.allow_start:
            raise conflict("managed_runtime_start_disabled")
        node = await self.nodes.authenticate(code, key)
        initial = await self.installations.find(id)
        if initial is None or initial.node_id != node.id:
            raise conflict("managed_installation_missing")
        scope = await self.scopes.initial(
            initial.core_id, runtime.max_profiles + 1
        )
        if len(scope.profiles) > runtime.max_profiles:
            raise conflict("managed_runtime_snapshot_capacity")
        customer_ids = sorted(
            {
                customer_id
                for owner in scope.owners
                for customer_id in (
                    owner.customer_id,
                    owner.payer_customer_id or owner.customer_id,
                )
            }
        )
        customers = await self.customers.locked_many(customer_ids)
        await self.nodes.locked(node.id)
        node = await self.nodes.authenticate(code, key)
        state = await self.states.locked(initial.core_id)
        owners = await self.scopes.lock_subscriptions(
            [owner.subscription_id for owner in scope.owners]
        )
        if owners != scope.owners:
            raise conflict("managed_installation_scope_changed")
        configurations = await self.scopes.lock_configurations(
            initial.core_id, runtime.max_configurations + 1
        )
        if len(configurations) > runtime.max_configurations:
            raise conflict("managed_runtime_snapshot_capacity")
        profiles = await self.scopes.current_profiles(
            configurations, runtime.max_profiles + 1
        )
        if profiles != scope.profiles:
            raise conflict("managed_installation_scope_changed")
        assignment = await self.facts.assignment(
            data.profile_id, node.id, lock=True
        )
        if (
            assignment is None
            or assignment.configuration.core_id != initial.core_id
        ):
            raise conflict("managed_window_profile_invalid")
        subscription = await self.subscriptions.get_by_id(
            assignment.profile.subscription_id
        )
        if subscription is None:
            raise conflict("managed_window_subscription_missing")
        owner = next(
            (row for row in owners if row.subscription_id == subscription.id),
            None,
        )
        customer = next(
            (row for row in customers if row.id == subscription.customer_id),
            None,
        )
        if (
            owner is None
            or owner.customer_id != subscription.customer_id
            or customer is None
        ):
            raise conflict("managed_installation_scope_changed")
        installation = await self.installations.locked(id)
        if (
            installation.core_id != initial.core_id
            or installation.node_id != node.id
        ):
            raise conflict("managed_installation_scope_changed")
        epoch_hint = await self.epochs.by_epoch(data.process_epoch)
        if epoch_hint is None:
            raise conflict("managed_window_epoch_invalid")
        epoch = await self.epochs.locked(epoch_hint.id)
        if (
            installation.state != "installed_closed"
            or epoch is None
            or epoch.installation_id != id
            or epoch.process_epoch != data.process_epoch
        ):
            raise conflict("managed_window_epoch_invalid")
        request_digest = await asyncio.to_thread(
            ManagedWindowEncoding.request_digest, id, data
        )
        existing = await self.windows.by_request(
            data.profile_id, data.generation, data.request_key
        )
        if existing is not None:
            if (
                existing.request_sha256 != request_digest
                or existing.epoch_id != epoch.id
            ):
                raise conflict("managed_window_request_reused")
            result = await asyncio.to_thread(
                ManagedWindowEncoding.output,
                ManagedWindowModel.model_validate(existing.model_dump()),
                self.settings.configuration_encryption_key,
            )
            return result
        if await self.epoch_seals.by_epoch(epoch.id) is not None:
            raise conflict("managed_window_epoch_sealed")
        previous = await self.windows.initial_for_profile_epoch(
            data.profile_id, epoch.id
        )
        if previous is not None:
            raise conflict("managed_window_successor_unavailable")
        now = datetime.now(UTC).replace(tzinfo=None)
        task = None
        request = None
        provision_claim = None
        encrypted_claim = None
        fulfillment = None
        if data.provision_task_id is not None:
            if policy.paid_mode != "strict_admission":
                raise conflict("managed_paid_admission_disabled")
            request = await self.requests.by_generation(
                subscription.id, data.generation
            )
            task = await self.tasks.locked(data.provision_task_id)
            if (
                request is None
                or task is None
                or task.request_id != request.id
                or task.node_id != node.id
                or task.profile_id != data.profile_id
                or task.configuration_id != assignment.configuration.id
                or task.configuration_revision
                != assignment.configuration.revision
                or task.action != "apply"
                or request.state not in {"dispatching", "active"}
                or request.deadline_at <= now
                or task.state not in {"queued", "failed", "leased"}
                or task.available_at > now
                or task.state == "leased"
                and task.claim_until is not None
                and task.claim_until > now
                or not subscription.provisioning_managed
            ):
                raise conflict("managed_provision_not_claimable")
            fulfillment = FulfillmentPolicy.model_validate_json(
                request.policy_json
            )
            if task.attempts >= fulfillment.max_attempts:
                raise conflict("provision_attempts_exhausted")
        rollover_continuation = False
        if task is None and epoch.previous_epoch_id is not None:
            previous_epoch = await self.epochs.find(epoch.previous_epoch_id)
            rollover_continuation = (
                previous_epoch is not None
                and previous_epoch.installation_id == installation.id
                and await self.epoch_seals.by_epoch(previous_epoch.id)
                is not None
            )
        if (
            not node.is_enabled
            or not CustomerAccessPolicy.services_available(customer)
            or subscription.status
            not in (
                {"pending_provision", "active"}
                if task is not None
                else {"active"}
            )
            or task is None
            and subscription.provisioning_managed
            and not rollover_continuation
            or subscription.renewal_count != data.generation
            or subscription.expires_at is not None
            and subscription.expires_at <= now
            or state.automation_paused
            or epoch.installed_closed_at
            + timedelta(seconds=policy.observation_seconds)
            <= now
        ):
            raise conflict("managed_window_entitlement_inactive")
        pending = await self.commands.outstanding(initial.core_id)
        if pending is not None:
            raise conflict("managed_window_runtime_pending")
        expectation = await asyncio.to_thread(
            ManagedInstallationEncoding.decode,
            installation.encrypted_manifest,
            self.settings.configuration_encryption_key,
        )
        if (
            expectation.runtime_state_revision != state.revision
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
            raise conflict("managed_window_policy_changed")
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
        member = next(
            (
                row
                for row in expectation.profiles
                if row.binding.profile_id == data.profile_id
            ),
            None,
        )
        if member is None or (
            member.binding.generation != data.generation
            or member.binding.configuration_id != assignment.configuration.id
            or member.binding.configuration_revision
            != assignment.configuration.revision
        ):
            raise conflict("managed_window_profile_invalid")
        quota = (
            QuotaPolicy.model_validate_json(subscription.quota_policy_json)
            if subscription.quota_policy_json
            else self.settings.usage.policy
        )
        if (
            quota.mode != "reserved"
            or data.requested_bytes > quota.grant_bytes
        ):
            raise conflict("managed_window_quota_policy")
        if await self.facts.has_open_profile(data.profile_id, data.generation):
            raise conflict("usage_final_report_required")
        reserved = await self.facts.reserved_bytes(
            subscription.id, data.generation, ["reserved"]
        )
        if subscription.quota_bytes is not None and data.requested_bytes > max(
            subscription.quota_bytes - subscription.used_bytes - reserved, 0
        ):
            raise conflict("usage_quota_unavailable")
        until = min(
            now + timedelta(seconds=quota.grant_seconds),
            now + timedelta(milliseconds=policy.capacity.max_validity_ms),
            subscription.expires_at
            or now + timedelta(seconds=quota.grant_seconds),
        )
        if (
            task is not None
            and request is not None
            and fulfillment is not None
        ):
            until = min(until, request.deadline_at)
            if (
                subscription.expires_at is None
                and subscription.duration_days is not None
            ):
                until = min(
                    until, now + timedelta(days=subscription.duration_days)
                )
            provision_claim = ManagedProvisionClaim(
                task_id=task.id,
                request_id=request.id,
                claim_token=secrets.token_urlsafe(32),
                claim_until=min(
                    until, now + timedelta(seconds=fulfillment.claim_seconds)
                ).replace(tzinfo=UTC),
            )
            encrypted_claim = await asyncio.to_thread(
                encrypt,
                provision_claim.model_dump_json(),
                self.settings.configuration_encryption_key,
            )
            claim_hash = await asyncio.to_thread(
                hash_sha256, provision_claim.claim_token
            )
            await self.tasks.change(
                task,
                ProvisionTaskModel.patch(
                    state="leased",
                    attempts=task.attempts + 1,
                    claim_hash=claim_hash,
                    claim_until=provision_claim.claim_until.replace(
                        tzinfo=None
                    ),
                    installed_revision_id=installation.runtime_revision_id,
                    membership_sha256=member.membership_sha256,
                    ack_sha256=None,
                    last_outcome=None,
                    acknowledged_at=None,
                ),
            )
        grant = await self.grants.create(
            UsageGrantModel(
                subscription_id=subscription.id,
                profile_id=data.profile_id,
                node_id=node.id,
                generation=data.generation,
                configuration_revision=assignment.configuration.revision,
                request_key=data.request_key,
                mode="reserved",
                allocated_bytes=data.requested_bytes,
                valid_until=until,
                installed_revision_id=installation.runtime_revision_id,
                process_epoch=data.process_epoch,
            )
        )
        window = ManagedWindowWire(
            enforcement_mode="strict_decoded",
            enforcement_sha256=policy.enforcement_sha256,
            grant_id=grant.id,
            window_id=secrets.token_hex(16),
            epoch=data.process_epoch,
            installation=expectation.installation,
            binding=member.binding,
            membership_sha256=member.membership_sha256,
            profile_sha256=member.profile_sha256,
            baseline_upload_bytes=0,
            baseline_download_bytes=0,
            allocated_bytes=data.requested_bytes,
            issued_at=now.replace(tzinfo=UTC),
            valid_until=until.replace(tzinfo=UTC),
            predecessor=None,
        )
        encrypted, digest, byte_count = await asyncio.to_thread(
            ManagedWindowEncoding.encode,
            window,
            self.settings.configuration_encryption_key,
        )
        if byte_count > policy.capacity.max_window_bytes:
            raise conflict("managed_window_capacity")
        stored = await self.windows.create(
            ManagedWindowModel(
                provision_task_id=data.provision_task_id,
                encrypted_provision_claim=encrypted_claim,
                epoch_id=epoch.id,
                grant_id=grant.id,
                profile_id=data.profile_id,
                subscription_id=subscription.id,
                generation=data.generation,
                window_id=window.window_id,
                request_key=data.request_key,
                request_sha256=request_digest,
                window_sha256=digest,
                baseline_upload_bytes=0,
                baseline_download_bytes=0,
                allocated_bytes=data.requested_bytes,
                issued_at=now,
                valid_until=until,
                encrypted_window=encrypted,
            )
        )
        result = await asyncio.to_thread(
            ManagedWindowEncoding.output,
            ManagedWindowModel.model_validate(stored.model_dump()),
            self.settings.configuration_encryption_key,
        )
        return result
