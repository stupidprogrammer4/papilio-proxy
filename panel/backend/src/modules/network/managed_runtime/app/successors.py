"""Reserved continuation with exact finality and unchanged paid attribution."""

import asyncio
import secrets
from datetime import UTC, datetime, timedelta

from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional

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
from src.modules.network.managed_runtime.app.successor_encoding import (
    ManagedSuccessorEncoding,
)
from src.modules.network.managed_runtime.app.window_encoding import (
    ManagedWindowEncoding,
)
from src.modules.network.managed_runtime.domain.contracts import (
    ManagedPredecessor,
)
from src.modules.network.managed_runtime.domain.models import (
    ManagedWindowModel,
)
from src.modules.network.managed_runtime.domain.successors import (
    ManagedSuccessorAdmissionFacts,
    ManagedSuccessorWindowCreate,
    ManagedSuccessorWindowFacts,
    ManagedSuccessorWindowOut,
)
from src.modules.network.managed_runtime.domain.wire import ManagedWindowWire
from src.modules.network.managed_runtime.infra.scopes import (
    ManagedInstallationScopeReader,
)
from src.modules.network.managed_runtime.infra.successor_reads import (
    ManagedSuccessorReader,
)
from src.modules.network.managed_runtime.interfaces import (
    IManagedAdmissionService,
    IManagedBarrierService,
    IManagedEpochSealService,
    IManagedEpochService,
    IManagedInstallationService,
    IManagedWindowService,
)
from src.modules.network.nodes.interfaces import INodeService
from src.modules.network.provisioning.infra.mysql import (
    ProvisionRequestRepository,
    ProvisionTaskRepository,
)
from src.modules.network.usage.domain.models import UsageGrantModel
from src.modules.network.usage.infra.mysql import UsageGrantRepository
from src.modules.network.usage.infra.readers import UsageFactsReader
from src.modules.sales.catalog.domain.policies import QuotaPolicy
from src.modules.sales.subscriptions.infra.mysql import SubscriptionRepository


class ManagedSuccessorWindowCommand:
    def __init__(
        self,
        installations: IManagedInstallationService,
        epochs: IManagedEpochService,
        epoch_seals: IManagedEpochSealService,
        windows: IManagedWindowService,
        barriers: IManagedBarrierService,
        admissions: IManagedAdmissionService,
        chains: ManagedSuccessorReader,
        scopes: ManagedInstallationScopeReader,
        customers: ICustomerService,
        nodes: INodeService,
        states: IRuntimeStateService,
        revisions: IRuntimeRevisionService,
        commands: IRuntimeCommandService,
        snapshots: RuntimeSnapshotReader,
        grants: UsageGrantRepository,
        subscriptions: SubscriptionRepository,
        facts: UsageFactsReader,
        tasks: ProvisionTaskRepository,
        requests: ProvisionRequestRepository,
        settings: PapilioSettings,
    ) -> None:
        self.installations, self.epochs, self.epoch_seals, self.windows = (
            installations,
            epochs,
            epoch_seals,
            windows,
        )
        self.barriers, self.admissions, self.chains = (
            barriers,
            admissions,
            chains,
        )
        self.scopes, self.customers, self.nodes = scopes, customers, nodes
        self.states, self.revisions, self.commands = (
            states,
            revisions,
            commands,
        )
        self.snapshots, self.grants, self.subscriptions = (
            snapshots,
            grants,
            subscriptions,
        )
        self.facts, self.tasks, self.requests, self.settings = (
            facts,
            tasks,
            requests,
            settings,
        )

    @handle_conflicts
    @transactional
    async def issue(
        self,
        code: str,
        key: str,
        predecessor_window_id: str,
        data: ManagedSuccessorWindowCreate,
    ) -> ManagedSuccessorWindowOut:
        policy = self.settings.managed_adapter
        runtime = self.settings.core_runtime
        live_enabled = (
            policy is not None
            and policy.enabled
            and policy.window_mode == "reserved"
            and policy.successor_policy.mode == "bounded"
            and policy.successor_policy.limits is not None
            and runtime is not None
            and runtime.enabled
            and runtime.allow_start
        )
        node = await self.nodes.authenticate(code, key)
        hint_row = await self.windows.by_identity(predecessor_window_id)
        if hint_row is None:
            raise conflict("managed_window_missing")
        hint = ManagedSuccessorWindowFacts.model_validate(
            hint_row.model_dump()
        )
        epoch_hint = await self.epochs.find(hint.epoch_id)
        if epoch_hint is None:
            raise conflict("managed_window_epoch_missing")
        initial = await self.installations.find(epoch_hint.installation_id)
        subscription_hint = await self.subscriptions.get_by_id(
            hint.subscription_id
        )
        if (
            initial is None
            or initial.node_id != node.id
            or subscription_hint is None
        ):
            raise conflict("managed_window_node_mismatch")
        initial_root = await self.chains.initial_hint(
            hint.profile_id, hint.epoch_id
        )
        if initial_root is None:
            raise conflict("managed_successor_chain_invalid")
        installation_id, core_id, epoch_id = (
            initial.id,
            initial.core_id,
            epoch_hint.id,
        )
        scope = None
        scope_capacity_exceeded = False
        scope_changed = False
        if live_enabled and runtime is not None:
            scope = await self.scopes.initial(
                core_id, runtime.max_profiles + 1
            )
            scope_capacity_exceeded = (
                len(scope.profiles) > runtime.max_profiles
            )
        customer_id, payer_id = (
            subscription_hint.customer_id,
            subscription_hint.payer_customer_id,
        )
        customer_ids = {customer_id, payer_id or customer_id}
        if scope is not None:
            customer_ids.update(
                {
                    id
                    for owner in scope.owners
                    for id in (
                        owner.customer_id,
                        owner.payer_customer_id or owner.customer_id,
                    )
                }
            )
        customers = await self.customers.locked_many(sorted(customer_ids))
        await self.nodes.locked(node.id)
        node = await self.nodes.authenticate(code, key)
        state = await self.states.locked(core_id)
        if scope is not None and runtime is not None:
            owners = await self.scopes.lock_subscriptions(
                sorted(
                    {row.subscription_id for row in scope.owners}
                    | {hint.subscription_id}
                )
            )
            scope_changed = owners != scope.owners
            configurations = await self.scopes.lock_configurations(
                core_id, runtime.max_configurations + 1
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
        paid_request = None
        paid_task = None
        if initial_root.provision_task_id is not None:
            paid_request = await self.requests.by_generation(
                subscription.id, initial_root.generation
            )
            paid_task = await self.tasks.locked(initial_root.provision_task_id)
        installation = await self.installations.locked(installation_id)
        epoch = await self.epochs.locked(epoch_id)
        predecessor = await self.windows.locked(hint.id)
        if (
            epoch is None
            or predecessor is None
            or epoch.installation_id != installation.id
            or installation.node_id != node.id
            or installation.core_id != core_id
            or predecessor.window_id != predecessor_window_id
            or predecessor.epoch_id != epoch.id
            or predecessor.subscription_id != subscription.id
            or predecessor.profile_id != hint.profile_id
            or predecessor.generation != hint.generation
            or epoch.process_epoch != data.acceptance.epoch
            or predecessor.profile_id != data.acceptance.profile_id
            or installation.state != "installed_closed"
        ):
            raise conflict("managed_successor_chain_invalid")
        request_digest = await asyncio.to_thread(
            ManagedSuccessorEncoding.request_digest,
            predecessor_window_id,
            data,
        )
        existing = await self.windows.by_request(
            predecessor.profile_id, predecessor.generation, data.request_key
        )
        if existing is not None:
            if (
                existing.request_sha256 != request_digest
                or existing.epoch_id != epoch.id
            ):
                raise conflict("managed_window_request_reused")
            result = await asyncio.to_thread(
                ManagedSuccessorEncoding.output,
                ManagedSuccessorWindowFacts.model_validate(
                    existing.model_dump()
                ),
                self.settings.configuration_encryption_key,
            )
            return result
        if (
            policy is None
            or not policy.enabled
            or policy.window_mode != "reserved"
            or policy.successor_policy.mode != "bounded"
            or policy.successor_policy.limits is None
        ):
            raise conflict("managed_successor_disabled")
        if runtime is None or not runtime.enabled or not runtime.allow_start:
            raise conflict("managed_runtime_start_disabled")
        limits = policy.successor_policy.limits
        if scope_capacity_exceeded:
            raise conflict("managed_runtime_snapshot_capacity")
        if (
            scope_changed
            or scope is None
            or not any(
                row.profile_id == hint.profile_id
                and row.subscription_id == hint.subscription_id
                for row in scope.profiles
            )
        ):
            raise conflict("managed_installation_scope_changed")
        chain = await self.chains.locked_epoch(
            epoch.id, limits.max_windows_per_epoch + 1
        )
        profile_chain = tuple(
            row
            for row in chain.windows
            if row.profile_id == predecessor.profile_id
            and row.generation == predecessor.generation
        )
        roots = tuple(
            row for row in profile_chain if row.predecessor_id is None
        )
        root = next((row for row in roots), None)
        tip = (
            max(profile_chain, key=lambda row: row.id)
            if profile_chain
            else None
        )
        if (
            root is None
            or tip is None
            or len(roots) != 1
            or root.id != initial_root.id
            or root.provision_task_id != initial_root.provision_task_id
            or root.encrypted_provision_claim
            != initial_root.encrypted_provision_claim
            or tip.id != predecessor.id
            or any(
                row.subscription_id != subscription.id for row in profile_chain
            )
            or any(
                row.provision_task_id != root.provision_task_id
                or row.encrypted_provision_claim
                != root.encrypted_provision_claim
                for row in profile_chain
            )
        ):
            raise conflict("managed_successor_predecessor_stale")
        now = datetime.now(UTC).replace(tzinfo=None)
        if (
            len(chain.windows) >= limits.max_windows_per_epoch
            or len(profile_chain) >= limits.max_windows_per_profile_epoch
            or now
            >= epoch.installed_closed_at
            + timedelta(seconds=limits.max_epoch_seconds)
            or data.requested_bytes > limits.max_requested_bytes
        ):
            raise conflict("managed_successor_capacity")
        customer = next(
            (row for row in customers if row.id == customer_id), None
        )
        if (
            customer is None
            or not CustomerAccessPolicy.services_available(customer)
            or not node.is_enabled
            or subscription.status != "active"
            or subscription.renewal_count != predecessor.generation
            or subscription.expires_at is not None
            and subscription.expires_at <= now
            or state.automation_paused
        ):
            raise conflict("managed_window_entitlement_inactive")
        rollover_continuation = False
        if subscription.provisioning_managed:
            if epoch.previous_epoch_id is not None:
                previous_seal = await self.epoch_seals.by_epoch(
                    epoch.previous_epoch_id
                )
                if previous_seal is None:
                    raise conflict("managed_rollover_finality_missing")
                if (
                    root.provision_task_id is not None
                    or root.encrypted_provision_claim is not None
                ):
                    raise conflict("managed_rollover_paid_claim_unexpected")
                rollover_continuation = True
            if not rollover_continuation and (
                policy.paid_mode != "strict_admission"
                or root.provision_task_id is None
                or not root.encrypted_provision_claim
                or paid_request is None
                or paid_task is None
                or paid_request.state != "active"
                or paid_request.subscription_id != subscription.id
                or paid_request.generation != predecessor.generation
                or paid_task.request_id != paid_request.id
                or paid_task.node_id != node.id
                or paid_task.profile_id != predecessor.profile_id
                or paid_task.action != "apply"
                or paid_task.state != "applied"
                or paid_task.installed_revision_id
                != installation.runtime_revision_id
            ):
                raise conflict("managed_successor_paid_root_invalid")
        elif root.provision_task_id is not None:
            raise conflict("managed_successor_paid_root_invalid")
        if await self.commands.outstanding(core_id) is not None:
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
        assignment = await self.facts.assignment(
            predecessor.profile_id, node.id, lock=True
        )
        if assignment is None or assignment.configuration.core_id != core_id:
            raise conflict("managed_window_profile_invalid")
        member = next(
            (
                row
                for row in expectation.profiles
                if row.binding.profile_id == predecessor.profile_id
            ),
            None,
        )
        if (
            member is None
            or member.binding.generation != predecessor.generation
            or member.binding.configuration_id != assignment.configuration.id
            or member.binding.configuration_revision
            != assignment.configuration.revision
            or assignment.profile.subscription_id != subscription.id
            or paid_task is not None
            and (
                paid_task.configuration_id != assignment.configuration.id
                or paid_task.configuration_revision
                != assignment.configuration.revision
                or paid_task.membership_sha256 != member.membership_sha256
            )
        ):
            raise conflict("managed_window_profile_invalid")
        revision = await self.revisions.get(
            installation.runtime_revision_id, installation.core_id
        )
        if (
            revision.encrypted_memberships is None
            or revision.membership_sha256 is None
        ):
            raise conflict("managed_runtime_snapshot_stale")
        snapshot = await self.snapshots.facts(
            core_id, runtime.max_configurations + 1, runtime.max_profiles + 1
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
        if subscription.provisioning_managed and not rollover_continuation:
            admission = await self.admissions.by_window(root.id)
            if admission is None:
                raise conflict("managed_successor_paid_root_invalid")
            try:
                await asyncio.to_thread(
                    ManagedSuccessorEncoding.verify_paid_root,
                    root,
                    ManagedSuccessorAdmissionFacts.model_validate(
                        admission.model_dump()
                    ),
                    expectation,
                    epoch.receipt_sha256,
                    self.settings.configuration_encryption_key,
                )
            except (ValueError, TypeError, KeyError):
                raise conflict("managed_successor_paid_root_invalid") from None
        grant = await self.grants.locked(predecessor.grant_id)
        if (
            grant is None
            or not grant.is_closed
            or grant.mode != "reserved"
            or grant.node_id != node.id
            or grant.subscription_id != subscription.id
            or grant.profile_id != predecessor.profile_id
            or grant.generation != predecessor.generation
            or grant.process_epoch != epoch.process_epoch
            or grant.allocated_bytes != predecessor.allocated_bytes
            or grant.sequence != 1
        ):
            raise conflict("managed_successor_finality_required")
        barrier = await self.barriers.by_identity(
            epoch.id, data.acceptance.barrier_id
        )
        if (
            barrier is None
            or barrier.acceptance_id != data.acceptance.acceptance_id
        ):
            raise conflict("managed_successor_finality_required")
        acceptance = ManagedPredecessor(
            acceptance_id=barrier.acceptance_id,
            epoch=epoch.process_epoch,
            profile_id=predecessor.profile_id,
            barrier_id=barrier.barrier_id,
            snapshot_sha256=barrier.snapshot_sha256,
        )
        try:
            evidence = await asyncio.to_thread(
                ManagedSuccessorEncoding.evidence,
                ManagedSuccessorWindowFacts.model_validate(
                    predecessor.model_dump()
                ),
                acceptance,
                barrier.encrypted_receipt,
                grant.upload_bytes,
                grant.download_bytes,
                self.settings.configuration_encryption_key,
            )
            baseline = await asyncio.to_thread(
                ManagedSuccessorEncoding.verify_predecessor,
                predecessor_window_id,
                data,
                evidence,
                expectation,
            )
        except (ValueError, TypeError, KeyError):
            raise conflict("managed_successor_receipt_invalid") from None
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
        if await self.facts.has_open_profile(
            predecessor.profile_id, predecessor.generation
        ):
            raise conflict("usage_final_report_required")
        reserved = await self.facts.reserved_bytes(
            subscription.id, predecessor.generation, ["reserved"]
        )
        if subscription.quota_bytes is not None and data.requested_bytes > max(
            subscription.quota_bytes - subscription.used_bytes - reserved, 0
        ):
            raise conflict("usage_quota_unavailable")
        until = min(
            now + timedelta(seconds=quota.grant_seconds),
            now + timedelta(milliseconds=policy.capacity.max_validity_ms),
            epoch.installed_closed_at
            + timedelta(seconds=limits.max_epoch_seconds),
            subscription.expires_at
            or now + timedelta(seconds=quota.grant_seconds),
        )
        created_grant = await self.grants.create(
            UsageGrantModel(
                subscription_id=subscription.id,
                profile_id=predecessor.profile_id,
                node_id=node.id,
                generation=predecessor.generation,
                configuration_revision=assignment.configuration.revision,
                request_key=data.request_key,
                mode="reserved",
                allocated_bytes=data.requested_bytes,
                valid_until=until,
                installed_revision_id=installation.runtime_revision_id,
                process_epoch=epoch.process_epoch,
            )
        )
        window = ManagedWindowWire(
            enforcement_mode="strict_decoded",
            enforcement_sha256=policy.enforcement_sha256,
            grant_id=created_grant.id,
            window_id=secrets.token_hex(16),
            epoch=epoch.process_epoch,
            installation=expectation.installation,
            binding=member.binding,
            membership_sha256=member.membership_sha256,
            profile_sha256=member.profile_sha256,
            baseline_upload_bytes=baseline.upload_bytes,
            baseline_download_bytes=baseline.download_bytes,
            allocated_bytes=data.requested_bytes,
            issued_at=now.replace(tzinfo=UTC),
            valid_until=until.replace(tzinfo=UTC),
            predecessor=baseline.predecessor,
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
                provision_task_id=root.provision_task_id,
                encrypted_provision_claim=root.encrypted_provision_claim,
                epoch_id=epoch.id,
                grant_id=created_grant.id,
                profile_id=predecessor.profile_id,
                subscription_id=subscription.id,
                generation=predecessor.generation,
                window_id=window.window_id,
                request_key=data.request_key,
                request_sha256=request_digest,
                window_sha256=digest,
                baseline_upload_bytes=baseline.upload_bytes,
                baseline_download_bytes=baseline.download_bytes,
                allocated_bytes=data.requested_bytes,
                issued_at=now,
                valid_until=until,
                predecessor_id=barrier.id,
                encrypted_window=encrypted,
            )
        )
        result = await asyncio.to_thread(
            ManagedSuccessorEncoding.output,
            ManagedSuccessorWindowFacts.model_validate(stored.model_dump()),
            self.settings.configuration_encryption_key,
        )
        return result
