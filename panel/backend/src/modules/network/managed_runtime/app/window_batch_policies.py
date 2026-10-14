"""Pure policies and plans for atomic initial-window batches."""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TypeAlias

from src.config.settings import PapilioSettings
from src.modules.accounts.customers.domain.models import CustomerModel
from src.modules.network.core_runtime.app.commands import conflict
from src.modules.network.core_runtime.domain.models import (
    CoreRuntimeStateModel,
)
from src.modules.network.managed_runtime.domain.installations import (
    ManagedAdapterPolicy,
    ManagedInstallationExpectation,
)
from src.modules.network.managed_runtime.domain.models import (
    ManagedEpochModel,
    ManagedInstallationModel,
    ManagedWindowModel,
)
from src.modules.network.managed_runtime.domain.results import (
    ManagedWindowRequestIdentity,
)
from src.modules.network.managed_runtime.domain.scopes import (
    ManagedProfileScope,
    ManagedSubscriptionOwner,
)
from src.modules.network.managed_runtime.domain.windows import (
    ManagedInitialWindowCreate,
    ManagedProvisionClaim,
)
from src.modules.network.managed_runtime.domain.wire import (
    ManagedClosedProfileWire,
)
from src.modules.network.nodes.domain.models import NodeModel
from src.modules.network.provisioning.domain.models import (
    ProvisionRequestModel,
    ProvisionTaskModel,
)
from src.modules.network.usage.domain.models import UsageGrantModel
from src.modules.network.usage.domain.results import (
    ProfileUsageAssignment,
    UsageGrantAllocationKey,
)
from src.modules.sales.catalog.domain.policies import (
    FulfillmentPolicy,
    QuotaPolicy,
)
from src.modules.sales.subscriptions.domain.models import SubscriptionModel

WindowPlanInput: TypeAlias = tuple[
    ManagedInitialWindowCreate,
    ProfileUsageAssignment,
    SubscriptionModel,
    ManagedClosedProfileWire,
]


@dataclass(frozen=True, slots=True)
class WindowPlan:
    request: ManagedInitialWindowCreate
    request_sha256: str
    subscription: SubscriptionModel
    configuration_revision: int
    membership: ManagedClosedProfileWire
    valid_until: datetime
    task: ProvisionTaskModel | None
    claim: ManagedProvisionClaim | None


class ManagedInitialWindowBatchPolicy:
    def __init__(self, settings: PapilioSettings) -> None:
        self.settings = settings

    @staticmethod
    def identity(
        item: ManagedInitialWindowCreate,
    ) -> ManagedWindowRequestIdentity:
        return ManagedWindowRequestIdentity(
            item.profile_id, item.generation, item.request_key
        )

    @staticmethod
    def identity_from_row(
        row: ManagedWindowModel,
    ) -> ManagedWindowRequestIdentity:
        return ManagedWindowRequestIdentity(
            row.profile_id, row.generation, row.request_key
        )

    @staticmethod
    def grant_key(
        request: ManagedInitialWindowCreate,
    ) -> UsageGrantAllocationKey:
        return UsageGrantAllocationKey(
            request.profile_id, request.generation, request.request_key
        )

    @staticmethod
    def grant_key_from_row(row: UsageGrantModel) -> UsageGrantAllocationKey:
        return UsageGrantAllocationKey(
            row.profile_id, row.generation, row.request_key
        )

    @staticmethod
    def customer_ids(
        owners: tuple[ManagedSubscriptionOwner, ...],
    ) -> list[int]:
        return sorted(
            {
                customer_id
                for owner in owners
                for customer_id in (
                    owner.customer_id,
                    owner.payer_customer_id or owner.customer_id,
                )
            }
        )

    @staticmethod
    def validate_installation_membership(
        requests: list[ManagedInitialWindowCreate],
        profiles: tuple[ManagedProfileScope, ...],
        core_id: int,
        assignments: dict[int, ProfileUsageAssignment],
    ) -> None:
        profile_scope = {row.profile_id: row for row in profiles}
        for request in requests:
            scope = profile_scope.get(request.profile_id)
            assignment = assignments.get(request.profile_id)
            if (
                scope is None
                or assignment is None
                or assignment.configuration.core_id != core_id
                or scope.configuration_id != assignment.configuration.id
                or scope.subscription_id != assignment.profile.subscription_id
            ):
                raise conflict("managed_window_profile_invalid")

    @staticmethod
    def validate_entitlements(
        requests: list[ManagedInitialWindowCreate],
        assignments: dict[int, ProfileUsageAssignment],
        subscriptions: dict[int, SubscriptionModel],
        customers: dict[int, CustomerModel],
        node: NodeModel,
        state: CoreRuntimeStateModel,
        closed_at: datetime,
        observation_seconds: int,
        rollover_continuation: bool,
        now: datetime,
    ) -> None:
        for request in requests:
            assignment = assignments[request.profile_id]
            subscription = subscriptions.get(
                assignment.profile.subscription_id
            )
            customer = (
                customers.get(subscription.customer_id)
                if subscription is not None
                else None
            )
            if subscription is None or customer is None:
                raise conflict("managed_window_subscription_missing")
            if (
                not node.is_enabled
                or not customer.services_enabled
                or customer.service_hold_pending
                or subscription.status
                not in (
                    {"pending_provision", "active"}
                    if request.provision_task_id is not None
                    else {"active"}
                )
                or request.provision_task_id is None
                and subscription.provisioning_managed
                and not rollover_continuation
                or subscription.renewal_count != request.generation
                or subscription.expires_at is not None
                and subscription.expires_at <= now
                or state.automation_paused
                or closed_at + timedelta(seconds=observation_seconds) <= now
            ):
                raise conflict("managed_window_entitlement_inactive")

    @staticmethod
    def matches_policy(
        expectation: ManagedInstallationExpectation,
        policy: ManagedAdapterPolicy,
        state_revision: int,
        installation: ManagedInstallationModel,
    ) -> bool:
        return (
            expectation.runtime_state_revision == state_revision
            and expectation.runtime_revision_id
            == installation.runtime_revision_id
            and expectation.adapter_revision == policy.adapter_revision
            and expectation.source_commit == policy.source_commit
            and expectation.installation.executable_sha256
            == policy.executable_sha256
            and expectation.installation.materials_sha256
            == policy.materials_sha256
            and expectation.enforcement_sha256 == policy.enforcement_sha256
            and expectation.window_policy_sha256 == policy.window_policy_sha256
            and expectation.capacity == policy.capacity
            and expectation.claim_seconds == policy.claim_seconds
            and expectation.observation_seconds == policy.observation_seconds
            and expectation.clock_skew_seconds == policy.clock_skew_seconds
        )

    def plan_inputs(
        self,
        requests: list[ManagedInitialWindowCreate],
        assignments: dict[int, ProfileUsageAssignment],
        members: dict[int, ManagedClosedProfileWire],
        subscriptions: dict[int, SubscriptionModel],
        membership_sha256: str,
    ) -> list[WindowPlanInput]:
        inputs: list[WindowPlanInput] = []
        for request in requests:
            assignment = assignments[request.profile_id]
            member = members.get(request.profile_id)
            subscription = subscriptions.get(
                assignment.profile.subscription_id
            )
            if (
                member is None
                or subscription is None
                or member.binding.generation != request.generation
                or member.binding.configuration_id
                != assignment.configuration.id
                or member.binding.configuration_revision
                != assignment.configuration.revision
                or member.membership_sha256 != membership_sha256
            ):
                raise conflict("managed_window_profile_invalid")
            inputs.append((request, assignment, subscription, member))
        return inputs

    def build_plans(
        self,
        inputs: list[WindowPlanInput],
        digest_by_identity: dict[ManagedWindowRequestIdentity, str],
        tasks_by_id: dict[int, ProvisionTaskModel],
        requests_by_generation: dict[tuple[int, int], ProvisionRequestModel],
        node_id: int,
        policy: ManagedAdapterPolicy,
        now: datetime,
    ) -> list[WindowPlan]:
        plans = []
        for request, assignment, subscription, member in inputs:
            task = None
            provision_request = None
            claim = None
            until = self.valid_until(request, subscription, policy, now)
            if request.provision_task_id is not None:
                if policy.paid_mode != "strict_admission":
                    raise conflict("managed_paid_admission_disabled")
                task = tasks_by_id.get(request.provision_task_id)
                provision_request = requests_by_generation.get(
                    (subscription.id, request.generation)
                )
                if (
                    task is None
                    or provision_request is None
                    or task.request_id != provision_request.id
                    or task.node_id != node_id
                    or task.profile_id != request.profile_id
                    or task.configuration_id != assignment.configuration.id
                    or task.configuration_revision
                    != assignment.configuration.revision
                    or task.action != "apply"
                    or provision_request.state not in {"dispatching", "active"}
                    or provision_request.deadline_at <= now
                    or task.state not in {"queued", "failed", "leased"}
                    or task.available_at > now
                    or task.state == "leased"
                    and task.claim_until is not None
                    and task.claim_until > now
                    or not subscription.provisioning_managed
                ):
                    raise conflict("managed_provision_not_claimable")
                fulfillment = FulfillmentPolicy.model_validate_json(
                    provision_request.policy_json
                )
                if task.attempts >= fulfillment.max_attempts:
                    raise conflict("provision_attempts_exhausted")
                until = min(until, provision_request.deadline_at)
                if (
                    subscription.expires_at is None
                    and subscription.duration_days is not None
                ):
                    until = min(
                        until, now + timedelta(days=subscription.duration_days)
                    )
                claim = ManagedProvisionClaim(
                    task_id=task.id,
                    request_id=provision_request.id,
                    claim_token=secrets.token_urlsafe(32),
                    claim_until=min(
                        until,
                        now + timedelta(seconds=fulfillment.claim_seconds),
                    ).replace(tzinfo=UTC),
                )
            plans.append(
                WindowPlan(
                    request,
                    digest_by_identity[self.identity(request)],
                    subscription,
                    assignment.configuration.revision,
                    member,
                    until,
                    task,
                    claim,
                )
            )
        return plans

    def valid_until(
        self,
        request: ManagedInitialWindowCreate,
        subscription: SubscriptionModel,
        policy: ManagedAdapterPolicy,
        now: datetime,
    ) -> datetime:
        quota = (
            QuotaPolicy.model_validate_json(subscription.quota_policy_json)
            if subscription.quota_policy_json
            else self.settings.usage.policy
        )
        if request.requested_bytes > quota.grant_bytes:
            raise conflict("managed_window_quota_policy")
        until = min(
            now + timedelta(seconds=quota.grant_seconds),
            now + timedelta(milliseconds=policy.capacity.max_validity_ms),
            subscription.expires_at
            or now + timedelta(seconds=quota.grant_seconds),
        )
        return until

    @staticmethod
    def grant_rows(
        plans: list[WindowPlan],
        node_id: int,
        installation: ManagedInstallationModel,
        epoch: ManagedEpochModel,
    ) -> list[UsageGrantModel]:
        return [
            UsageGrantModel(
                subscription_id=plan.subscription.id,
                profile_id=plan.request.profile_id,
                node_id=node_id,
                generation=plan.request.generation,
                configuration_revision=plan.configuration_revision,
                request_key=plan.request.request_key,
                mode="reserved",
                allocated_bytes=plan.request.requested_bytes,
                valid_until=plan.valid_until,
                installed_revision_id=installation.runtime_revision_id,
                process_epoch=epoch.process_epoch,
            )
            for plan in plans
        ]

    def task_updates(
        self,
        plans: list[WindowPlan],
        installation: ManagedInstallationModel,
        claim_hashes: tuple[str | None, ...],
    ) -> list[ProvisionTaskModel]:
        updates = []
        for plan, claim_hash in zip(plans, claim_hashes, strict=True):
            if plan.task is None or plan.claim is None or claim_hash is None:
                continue
            updates.append(
                ProvisionTaskModel.patch(
                    id=plan.task.id,
                    state="leased",
                    attempts=plan.task.attempts + 1,
                    claim_hash=claim_hash,
                    claim_until=plan.claim.claim_until.replace(tzinfo=None),
                    installed_revision_id=installation.runtime_revision_id,
                    membership_sha256=plan.membership.membership_sha256,
                    ack_sha256=None,
                    last_outcome=None,
                    acknowledged_at=None,
                )
            )
        return updates
