"""Issue independent profile windows in one native transaction."""

import secrets
from datetime import UTC, datetime

import anyio
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional

from src.config.settings import PapilioSettings
from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.network.core_runtime.app.commands import conflict
from src.modules.network.core_runtime.interfaces import (
    IRuntimeCommandService,
    IRuntimeRevisionService,
    IRuntimeSnapshotQuery,
    IRuntimeStateService,
)
from src.modules.network.managed_runtime.app.admission_membership import (
    ManagedAdmissionMembership,
)
from src.modules.network.managed_runtime.app.installation_encoding import (
    ManagedInstallationEncoding,
)
from src.modules.network.managed_runtime.app.window_batch_policies import (
    ManagedInitialWindowBatchPolicy,
    WindowPlan,
    WindowPlanInput,
)
from src.modules.network.managed_runtime.app.window_computation import (
    compute_managed_window_batch_digest,
)
from src.modules.network.managed_runtime.app.window_encoding import (
    ManagedWindowEncoding,
)
from src.modules.network.managed_runtime.domain.installations import (
    ManagedInstallationExpectation,
)
from src.modules.network.managed_runtime.domain.models import (
    ManagedOperationBatchModel,
    ManagedWindowModel,
)
from src.modules.network.managed_runtime.domain.results import (
    ManagedInitialWindowBatchDigest,
    ManagedWindowRequestIdentity,
)
from src.modules.network.managed_runtime.domain.windows import (
    ManagedInitialWindowBatchCreate,
    ManagedInitialWindowBatchItemOut,
    ManagedInitialWindowBatchOut,
    ManagedInitialWindowCreate,
)
from src.modules.network.managed_runtime.domain.wire import (
    ManagedWindowWire,
)
from src.modules.network.managed_runtime.infra.scopes import (
    ManagedInstallationScopeReader,
)
from src.modules.network.managed_runtime.interfaces import (
    IManagedEpochSealService,
    IManagedEpochService,
    IManagedInstallationService,
    IManagedOperationBatchService,
    IManagedWindowService,
)
from src.modules.network.nodes.interfaces import INodeService
from src.modules.network.provisioning.domain.models import (
    ProvisionRequestModel,
    ProvisionTaskModel,
)
from src.modules.network.provisioning.domain.results import (
    ProvisionGenerationKey,
)
from src.modules.network.provisioning.interfaces import (
    IProvisionRequestBatchService,
    IProvisionTaskBatchService,
)
from src.modules.network.usage.domain.models import UsageGrantModel
from src.modules.network.usage.domain.results import (
    UsageGenerationKey,
    UsageGrantAllocationKey,
    UsageProfileGenerationKey,
)
from src.modules.network.usage.interfaces import (
    IUsageFactsReader,
    IUsageGrantService,
)
from src.modules.sales.catalog.domain.policies import (
    QuotaPolicy,
)
from src.modules.sales.subscriptions.interfaces import (
    ISubscriptionBatchService,
)


class ManagedInitialWindowBatchCommand:
    def __init__(
        self,
        installations: IManagedInstallationService,
        epochs: IManagedEpochService,
        windows: IManagedWindowService,
        operation_batches: IManagedOperationBatchService,
        scopes: ManagedInstallationScopeReader,
        epoch_seals: IManagedEpochSealService,
        customers: ICustomerService,
        nodes: INodeService,
        states: IRuntimeStateService,
        revisions: IRuntimeRevisionService,
        commands: IRuntimeCommandService,
        snapshots: IRuntimeSnapshotQuery,
        grants: IUsageGrantService,
        subscriptions: ISubscriptionBatchService,
        facts: IUsageFactsReader,
        tasks: IProvisionTaskBatchService,
        requests: IProvisionRequestBatchService,
        settings: PapilioSettings,
    ) -> None:
        self.policy = ManagedInitialWindowBatchPolicy(settings)
        self.installations = installations
        self.epochs = epochs
        self.windows = windows
        self.operation_batches = operation_batches
        self.scopes = scopes
        self.epoch_seals = epoch_seals
        self.customers = customers
        self.nodes = nodes
        self.states = states
        self.revisions = revisions
        self.commands = commands
        self.snapshots = snapshots
        self.grants = grants
        self.subscriptions = subscriptions
        self.facts = facts
        self.tasks = tasks
        self.requests = requests
        self.settings = settings

    @handle_conflicts
    @transactional
    async def issue(
        self,
        code: str,
        key: str,
        installation_id: int,
        data: ManagedInitialWindowBatchCreate,
    ) -> ManagedInitialWindowBatchOut:
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
        if (
            len(data.windows) > runtime.max_profiles
            or len(data.windows) > policy.capacity.max_profiles_per_barrier
        ):
            raise conflict("managed_runtime_snapshot_capacity")

        batch_digest = await compute_managed_window_batch_digest(
            installation_id, data.batch_request_key, tuple(data.windows)
        )
        node = await self.nodes.authenticate(code, key)
        initial = await self.installations.find(installation_id)
        if initial is None or initial.node_id != node.id:
            raise conflict("managed_installation_missing")
        scope = await self.scopes.initial(
            initial.core_id, runtime.max_profiles + 1
        )
        if len(scope.profiles) > runtime.max_profiles:
            raise conflict("managed_runtime_snapshot_capacity")

        customer_ids = self.policy.customer_ids(scope.owners)
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

        subscription_rows = await self.subscriptions.locked_many(
            [owner.subscription_id for owner in scope.owners]
        )
        customer_rows = {row.id: row for row in customers}
        subscriptions = {row.id: row for row in subscription_rows}
        for owner in scope.owners:
            subscription = subscriptions.get(owner.subscription_id)
            customer = customer_rows.get(owner.customer_id)
            if (
                subscription is None
                or subscription.customer_id != owner.customer_id
                or subscription.payer_customer_id != owner.payer_customer_id
                or customer is None
            ):
                raise conflict("managed_installation_scope_changed")

        installation = await self.installations.locked(installation_id)
        if (
            installation.core_id != initial.core_id
            or installation.node_id != node.id
        ):
            raise conflict("managed_installation_scope_changed")
        epoch_hint = await self.epochs.by_epoch(data.windows[0].process_epoch)
        if epoch_hint is None:
            raise conflict("managed_window_epoch_invalid")
        epoch = await self.epochs.locked(epoch_hint.id)
        if (
            installation.state != "installed_closed"
            or epoch is None
            or epoch.installation_id != installation_id
            or any(
                request.process_epoch != epoch.process_epoch
                for request in data.windows
            )
        ):
            raise conflict("managed_window_epoch_invalid")

        batch_row = await self.operation_batches.by_identity(
            installation_id, "initial_windows", data.batch_request_key
        )
        if batch_row is not None:
            result = await self._replay(batch_row, batch_digest, data)
            return result
        if await self.epoch_seals.by_epoch(epoch.id) is not None:
            raise conflict("managed_window_epoch_sealed")

        profile_ids = [item.profile_id for item in data.windows]
        assignments = await self.facts.assignment_many(
            profile_ids, node.id, lock=True
        )
        assignment_by_profile = {row.profile.id: row for row in assignments}
        if len(assignment_by_profile) != len(data.windows):
            raise conflict("managed_window_profile_invalid")
        self.policy.validate_installation_membership(
            data.windows,
            scope.profiles,
            initial.core_id,
            assignment_by_profile,
        )
        existing_requests = await self.windows.by_requests_many(
            [self.policy.identity(item) for item in data.windows]
        )
        if existing_requests:
            raise conflict("managed_window_batch_incomplete")
        existing_initials = await self.windows.initials_for_profiles_epoch(
            profile_ids, epoch.id
        )
        if existing_initials:
            raise conflict("managed_window_successor_unavailable")

        now = datetime.now(UTC).replace(tzinfo=None)
        rollover_continuation = False
        if (
            all(item.provision_task_id is None for item in data.windows)
            and epoch.previous_epoch_id is not None
        ):
            previous_epoch = await self.epochs.find(epoch.previous_epoch_id)
            rollover_continuation = (
                previous_epoch is not None
                and previous_epoch.installation_id == installation.id
                and await self.epoch_seals.by_epoch(previous_epoch.id)
                is not None
            )
        self.policy.validate_entitlements(
            data.windows,
            assignment_by_profile,
            subscriptions,
            customer_rows,
            node,
            state,
            epoch.installed_closed_at,
            policy.observation_seconds,
            rollover_continuation,
            now,
        )
        if await self.commands.outstanding(initial.core_id) is not None:
            raise conflict("managed_window_runtime_pending")
        expectation = await anyio.to_thread.run_sync(
            ManagedInstallationEncoding.decode,
            installation.encrypted_manifest,
            self.settings.configuration_encryption_key,
        )
        if not self.policy.matches_policy(
            expectation, policy, state.revision, installation
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
        membership_matches = await anyio.to_thread.run_sync(
            ManagedAdmissionMembership.matches,
            snapshot,
            revision.encrypted_memberships,
            revision.membership_sha256,
            revision.snapshot_sha256,
            now,
            self.settings.configuration_encryption_key,
        )
        if not membership_matches:
            raise conflict("managed_runtime_snapshot_stale")

        member_by_profile = {
            row.binding.profile_id: row for row in expectation.profiles
        }
        plan_inputs = self.policy.plan_inputs(
            data.windows,
            assignment_by_profile,
            member_by_profile,
            subscriptions,
            expectation.membership_sha256,
        )
        tasks_by_id, requests_by_generation = await self._load_provisioning(
            plan_inputs
        )
        digest_by_identity = {
            ManagedWindowRequestIdentity(
                item.profile_id, item.generation, item.request_key
            ): item.request_sha256
            for item in batch_digest.windows
        }
        plans = self.policy.build_plans(
            plan_inputs,
            digest_by_identity,
            tasks_by_id,
            requests_by_generation,
            node.id,
            policy,
            now,
        )
        await self._validate_quota(plans)
        grant_keys = [self.policy.grant_key(plan.request) for plan in plans]
        existing_grants = await self.grants.allocation_many(grant_keys)
        if existing_grants:
            raise conflict("managed_window_batch_incomplete")

        created_batch = await self.operation_batches.create(
            ManagedOperationBatchModel(
                installation_id=installation_id,
                epoch_id=epoch.id,
                operation="initial_windows",
                request_key=data.batch_request_key,
                request_sha256=batch_digest.request_sha256,
                item_count=len(data.windows),
                accepted_at=now,
            )
        )
        grant_rows = self.policy.grant_rows(
            plans, node.id, installation, epoch
        )
        await self.grants.create_many(grant_rows)
        allocated = await self.grants.allocation_many(grant_keys)
        grants_by_identity = {
            self.policy.grant_key_from_row(row): row for row in allocated
        }
        if len(grants_by_identity) != len(plans):
            raise conflict("managed_window_batch_incomplete")
        window_rows = await self._window_rows(
            plans,
            grants_by_identity,
            created_batch.id,
            epoch.id,
            expectation,
            policy.enforcement_sha256,
            self.settings.configuration_encryption_key,
        )
        claim_hashes = await anyio.to_thread.run_sync(
            ManagedWindowEncoding.hash_claim_tokens,
            tuple(
                plan.claim.claim_token if plan.claim is not None else None
                for plan in plans
            ),
        )
        task_updates = self.policy.task_updates(
            plans, installation, claim_hashes
        )
        if task_updates:
            await self.tasks.change_many(task_updates)
        await self.windows.create_many(window_rows)
        stored = await self.windows.by_operation_batch(created_batch.id)
        output = await self._output(
            data.batch_request_key, data.windows, stored
        )
        return output

    async def _replay(
        self,
        batch_row: ManagedOperationBatchModel,
        digest: ManagedInitialWindowBatchDigest,
        data: ManagedInitialWindowBatchCreate,
    ) -> ManagedInitialWindowBatchOut:
        if batch_row.request_sha256 != digest.request_sha256:
            raise conflict("managed_window_batch_reused")
        stored = await self.windows.by_operation_batch(batch_row.id)
        if len(stored) != batch_row.item_count or len(stored) != len(
            data.windows
        ):
            raise conflict("managed_window_batch_incomplete")
        stored_by_identity = {
            ManagedWindowRequestIdentity(
                row.profile_id, row.generation, row.request_key
            ): row
            for row in stored
        }
        requested = {self.policy.identity(item) for item in data.windows}
        if stored_by_identity.keys() != requested:
            raise conflict("managed_window_batch_incomplete")
        output = await self._output(
            data.batch_request_key, data.windows, stored
        )
        return output

    async def _output(
        self,
        batch_request_key: str,
        requests: list[ManagedInitialWindowCreate],
        rows: list[ManagedWindowModel],
    ) -> ManagedInitialWindowBatchOut:
        rows_by_identity = {
            self.policy.identity_from_row(row): row for row in rows
        }
        if len(rows_by_identity) != len(requests):
            raise conflict("managed_window_batch_incomplete")
        ordered = [
            rows_by_identity[self.policy.identity(item)] for item in requests
        ]
        detached = tuple(
            ManagedWindowModel.model_validate(row.model_dump())
            for row in ordered
        )
        outputs = await anyio.to_thread.run_sync(
            ManagedWindowEncoding.outputs,
            detached,
            self.settings.configuration_encryption_key,
        )
        return ManagedInitialWindowBatchOut(
            batch_request_key=batch_request_key,
            windows=[
                ManagedInitialWindowBatchItemOut(
                    profile_id=request.profile_id, window=output
                )
                for request, output in zip(requests, outputs, strict=True)
            ],
        )

    async def _load_provisioning(
        self, inputs: list[WindowPlanInput]
    ) -> tuple[
        dict[int, ProvisionTaskModel],
        dict[tuple[int, int], ProvisionRequestModel],
    ]:
        task_ids = [
            request.provision_task_id
            for request, _, _, _ in inputs
            if request.provision_task_id is not None
        ]
        tasks = await self.tasks.locked_many(task_ids)
        tasks_by_id = {row.id: row for row in tasks}
        generation_keys = sorted(
            {
                ProvisionGenerationKey(subscription.id, request.generation)
                for request, _, subscription, _ in inputs
                if request.provision_task_id is not None
            },
            key=lambda key: (key.subscription_id, key.generation),
        )
        provision_requests = await self.requests.by_generations(
            generation_keys
        )
        requests_by_generation = {
            (row.subscription_id, row.generation): row
            for row in provision_requests
        }
        return tasks_by_id, requests_by_generation

    async def _validate_quota(self, plans: list[WindowPlan]) -> None:
        profile_keys = [
            UsageProfileGenerationKey(
                plan.request.profile_id, plan.request.generation
            )
            for plan in plans
        ]
        open_profiles = await self.facts.has_open_profiles_many(profile_keys)
        if open_profiles:
            raise conflict("usage_final_report_required")
        generation_keys = sorted(
            {
                UsageGenerationKey(
                    plan.subscription.id, plan.request.generation
                )
                for plan in plans
            },
            key=lambda key: (key.subscription_id, key.generation),
        )
        reservations = await self.facts.reserved_bytes_many(
            generation_keys, ["reserved"]
        )
        reserved_by_generation = {
            (row.subscription_id, row.generation): row.allocated_bytes
            for row in reservations
        }
        requested_by_generation = {}
        for plan in plans:
            request = plan.request
            quota = (
                QuotaPolicy.model_validate_json(
                    plan.subscription.quota_policy_json
                )
                if plan.subscription.quota_policy_json
                else self.settings.usage.policy
            )
            if (
                quota.mode != "reserved"
                or request.requested_bytes > quota.grant_bytes
            ):
                raise conflict("managed_window_quota_policy")
            identity = (plan.subscription.id, request.generation)
            requested_by_generation[identity] = (
                requested_by_generation.get(identity, 0)
                + request.requested_bytes
            )
        for subscription_id, generation in requested_by_generation:
            subscription = next(
                plan.subscription
                for plan in plans
                if plan.subscription.id == subscription_id
                and plan.request.generation == generation
            )
            if subscription.quota_bytes is None:
                continue
            already_reserved = reserved_by_generation.get(
                (subscription_id, generation), 0
            )
            remaining = max(
                subscription.quota_bytes
                - subscription.used_bytes
                - already_reserved,
                0,
            )
            if (
                requested_by_generation[(subscription_id, generation)]
                > remaining
            ):
                raise conflict("usage_quota_unavailable")

    async def _window_rows(
        self,
        plans: list[WindowPlan],
        grants: dict[UsageGrantAllocationKey, UsageGrantModel],
        batch_id: int,
        epoch_id: int,
        expectation: ManagedInstallationExpectation,
        enforcement_sha256: str,
        encryption_key: str,
    ) -> list[ManagedWindowModel]:
        issued_at = datetime.now(UTC)
        pairs = []
        for plan in plans:
            request = plan.request
            grant = grants.get(self.policy.grant_key(request))
            if grant is None:
                raise conflict("managed_window_batch_incomplete")
            member = plan.membership
            wire = ManagedWindowWire(
                enforcement_mode="strict_decoded",
                enforcement_sha256=enforcement_sha256,
                grant_id=grant.id,
                window_id=secrets.token_hex(16),
                epoch=request.process_epoch,
                installation=expectation.installation,
                binding=member.binding,
                membership_sha256=member.membership_sha256,
                profile_sha256=member.profile_sha256,
                baseline_upload_bytes=0,
                baseline_download_bytes=0,
                allocated_bytes=request.requested_bytes,
                issued_at=issued_at,
                valid_until=plan.valid_until.replace(tzinfo=UTC),
                predecessor=None,
            )
            pairs.append((plan, grant, wire))
        encoded = await anyio.to_thread.run_sync(
            ManagedWindowEncoding.encode_many,
            tuple(wire for _, _, wire in pairs),
            encryption_key,
        )
        encrypted_claims = await anyio.to_thread.run_sync(
            ManagedWindowEncoding.encode_claims,
            tuple(
                plan.claim.model_dump_json()
                if plan.claim is not None
                else None
                for plan, _, _ in pairs
            ),
            encryption_key,
        )
        rows = []
        policy = self.settings.managed_adapter
        if policy is None:
            raise conflict("managed_window_disabled")
        for (plan, grant, wire), (
            encrypted,
            digest,
            byte_count,
        ), encrypted_claim in zip(
            pairs, encoded, encrypted_claims, strict=True
        ):
            if byte_count > policy.capacity.max_window_bytes:
                raise conflict("managed_window_capacity")
            rows.append(
                ManagedWindowModel(
                    operation_batch_id=batch_id,
                    provision_task_id=plan.task.id if plan.task else None,
                    encrypted_provision_claim=encrypted_claim,
                    epoch_id=epoch_id,
                    grant_id=grant.id,
                    profile_id=plan.request.profile_id,
                    subscription_id=plan.subscription.id,
                    generation=plan.request.generation,
                    window_id=wire.window_id,
                    request_key=plan.request.request_key,
                    request_sha256=plan.request_sha256,
                    window_sha256=digest,
                    baseline_upload_bytes=0,
                    baseline_download_bytes=0,
                    allocated_bytes=plan.request.requested_bytes,
                    issued_at=wire.issued_at.replace(tzinfo=None),
                    valid_until=plan.valid_until,
                    predecessor_id=None,
                    encrypted_window=encrypted,
                )
            )
        return rows
