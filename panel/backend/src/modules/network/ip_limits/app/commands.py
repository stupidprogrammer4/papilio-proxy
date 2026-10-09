import asyncio
from datetime import UTC, datetime, timedelta

from papilio.errors.exceptions import (
    ConflictException,
    NotFoundException,
    UnAuthorizedException,
)
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import hash_sha256, secure_compare

from src.config.settings import PapilioSettings
from src.modules.accounts.customers.app.policies import CustomerAccessPolicy
from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.network.ip_limits.domain.dtos import (
    IpAdmission,
    IpLimitChoice,
    IpManualBan,
    IpPolicyConfigureChoice,
)
from src.modules.network.ip_limits.domain.models import (
    IpLeaseStateModel,
    IpLimitPolicyModel,
    IpSessionModel,
)
from src.modules.network.ip_limits.domain.results import (
    IpAdmissionDecision,
    NodeSubscriptionAssignment,
)
from src.modules.network.ip_limits.infra.leases import IpLeaseStateRepository
from src.modules.network.ip_limits.infra.mysql import (
    IpLimitPolicyRepository,
    IpSessionRepository,
)
from src.modules.network.ip_limits.infra.readers import NodeSubscriptionReader
from src.modules.network.ip_limits.interfaces import (
    IIpAdmissionClock,
    IPurchasedIpPolicyService,
)
from src.modules.network.nodes.interfaces import INodeService
from src.modules.sales.subscriptions.infra.mysql import SubscriptionRepository


class IpLimitPolicyCommand:
    def __init__(
        self,
        subscriptions: SubscriptionRepository,
        policies: IpLimitPolicyRepository,
        sessions: IpSessionRepository,
        settings: PapilioSettings,
        purchased_ip: IPurchasedIpPolicyService,
        lease_states: IpLeaseStateRepository,
        clock: IIpAdmissionClock,
    ) -> None:
        self.subscriptions = subscriptions
        self.policies = policies
        self.sessions = sessions
        self.settings = settings
        self.purchased_ip = purchased_ip
        self.lease_states, self.clock = lease_states, clock

    @handle_conflicts
    @transactional
    async def configure(
        self, subscription_id: int, data: IpPolicyConfigureChoice
    ) -> IpLimitPolicyModel:
        subscription = await self.subscriptions.locked(subscription_id)
        if subscription is None:
            raise _missing("subscription", subscription_id)
        ceilings = self.settings.ip_limits
        if (
            data.max_ips > ceilings.max_ips_ceiling
            or data.lease_seconds > ceilings.max_lease_seconds
            or data.ban_seconds > ceilings.max_ban_seconds
        ):
            raise _conflict("ip_policy_capacity", subscription_id)
        existing = await self.policies.locked(subscription_id)
        previous: IpLimitPolicyModel | IpLimitChoice | None = existing
        previous_source = (
            "subscription_override" if existing else "legacy_unrestricted"
        )
        if previous is None:
            snapshot = await self.purchased_ip.current(subscription_id)
            if snapshot is not None:
                previous = await asyncio.to_thread(
                    IpLimitChoice.model_validate_json, snapshot.policy_json
                )
                previous_source = "purchased_snapshot"
        state = await self.lease_states.locked(subscription_id)
        if state is None:
            state = await self.lease_states.create(
                IpLeaseStateModel(
                    subscription_id=subscription_id, history_complete=False
                )
            )
        if state.pending_policy_json is not None:
            previous = (
                await asyncio.to_thread(
                    IpLimitChoice.model_validate_json,
                    state.previous_policy_json,
                )
                if state.previous_policy_json is not None
                else None
            )
            previous_source = state.previous_source or "legacy_unrestricted"
        preserve_presence = (
            previous is not None
            and previous.enabled
            and data.enabled
            and data.max_ips >= previous.max_ips
        )
        tightening = data.enabled and (
            previous is None
            or not previous.enabled
            or data.max_ips < previous.max_ips
        )
        now = await self.clock.now()
        transition_mode = (
            data.transition_mode or self.settings.ip_limits.transition_mode
        )
        blocked_reason = (
            "closed_receipts_unavailable"
            if transition_mode == "require_closed_receipts"
            else "legacy_lease_history_unknown"
            if not state.history_complete
            else None
        )
        needs_drain = tightening and (
            blocked_reason is not None
            or state.issued_until is not None
            and state.issued_until > now
        )
        requested_policy = IpLimitChoice.model_validate(
            data, from_attributes=True
        )
        target_json = await asyncio.to_thread(requested_policy.model_dump_json)
        previous_json = (
            await asyncio.to_thread(
                IpLimitChoice.model_validate(
                    previous, from_attributes=True
                ).model_dump_json
            )
            if previous is not None
            else None
        )
        await self.lease_states.change(
            state,
            IpLeaseStateModel.patch(
                pending_policy_json=target_json if needs_drain else None,
                previous_policy_json=previous_json if needs_drain else None,
                previous_source=previous_source if needs_drain else None,
                transition_mode=transition_mode if needs_drain else None,
                drain_until=state.issued_until
                if needs_drain and not blocked_reason
                else None,
                blocked_reason=blocked_reason if needs_drain else None,
            ),
        )
        changes = IpLimitPolicyModel(
            subscription_id=subscription_id, **requested_policy.model_dump()
        )
        if existing is None:
            result = await self.policies.create(changes)
        else:
            result = await self.policies.change(existing, changes)
        if not preserve_presence and not needs_drain:
            await self.sessions.expire_subscription(
                subscription_id,
                now,
            )
        return result


class IpAdmissionCommand:
    def __init__(
        self,
        subscriptions: SubscriptionRepository,
        policies: IpLimitPolicyRepository,
        sessions: IpSessionRepository,
        assignments: NodeSubscriptionReader,
        clock: IIpAdmissionClock,
        purchased_ip: IPurchasedIpPolicyService,
        nodes: INodeService,
        settings: PapilioSettings,
        customers: ICustomerService,
        lease_states: IpLeaseStateRepository,
    ) -> None:
        self.subscriptions = subscriptions
        self.policies = policies
        self.sessions = sessions
        self.assignments = assignments
        self.clock = clock
        self.purchased_ip = purchased_ip
        self.nodes = nodes
        self.settings = settings
        self.customers = customers
        self.lease_states = lease_states

    @handle_conflicts
    @transactional
    async def admit(
        self, node_code: str, agent_key: str, data: IpAdmission
    ) -> IpAdmissionDecision:
        node = await self.nodes.authenticate(node_code, agent_key)
        hint = await self.subscriptions.get_by_id(data.subscription_id)
        if hint is None:
            raise _missing("subscription", data.subscription_id)
        customer = await self.customers.locked(hint.customer_id)
        node = await self.nodes.locked(node.id)
        digest = await asyncio.to_thread(hash_sha256, agent_key)
        if node.code != node_code or not secure_compare(
            digest, node.agent_key_hash
        ):
            raise UnAuthorizedException(
                message="Node authorization changed while waiting.",
                message_code="node_unauthorized",
            )
        subscription = await self.subscriptions.locked(data.subscription_id)
        if subscription is None:
            raise _missing("subscription", data.subscription_id)
        if subscription.customer_id != customer.id:
            raise _conflict("ip_subscription_owner_changed", subscription.id)
        assignment_capacity = (
            self.settings.ip_limits.max_assignment_profiles
            or self.settings.operations.configuration_export_max_profiles
        )
        facts = await self.assignments.assignment_facts(
            node.id, subscription.id, assignment_capacity + 1
        )
        if len(facts) > assignment_capacity:
            raise _conflict("ip_assignment_capacity", subscription.id)
        if not facts:
            raise _conflict("node_subscription_unassigned", subscription.id)
        assignment = NodeSubscriptionAssignment(
            subscription_id=subscription.id,
            node_id=node.id,
            profile_count=len(facts),
            acknowledged_count=sum(
                row.applied_generation == subscription.renewal_count
                and row.applied_revision == row.configuration_revision
                for row in facts
            ),
        )
        now = await self.clock.now()
        if (
            not CustomerAccessPolicy.services_available(customer)
            or not node.is_enabled
            or subscription.status != "active"
            or (
                subscription.expires_at is not None
                and subscription.expires_at <= now
            )
            or subscription.provisioning_managed
            and assignment.acknowledged_count == 0
        ):
            return IpAdmissionDecision(
                subscription.id,
                data.source_ip,
                False,
                "entitlement_inactive",
                now,
            )
        if (
            subscription.quota_bytes is not None
            and subscription.used_bytes >= subscription.quota_bytes
        ):
            return IpAdmissionDecision(
                subscription.id, data.source_ip, False, "quota_exhausted", now
            )
        state = await self.lease_states.locked(subscription.id)
        if state is None:
            state = await self.lease_states.create(
                IpLeaseStateModel(
                    subscription_id=subscription.id, history_complete=False
                )
            )
        if state.pending_policy_json is not None:
            if state.blocked_reason is not None or (
                state.drain_until is not None and state.drain_until > now
            ):
                return IpAdmissionDecision(
                    subscription.id,
                    data.source_ip,
                    False,
                    state.blocked_reason or "ip_policy_draining",
                    state.drain_until or now,
                )
            await self.sessions.expire_subscription(subscription.id, now)
            state = await self.lease_states.change(
                state,
                IpLeaseStateModel.patch(
                    pending_policy_json=None,
                    previous_policy_json=None,
                    previous_source=None,
                    transition_mode=None,
                    drain_until=None,
                    blocked_reason=None,
                ),
            )
        policy: (
            IpLimitPolicyModel | IpLimitChoice | None
        ) = await self.policies.locked(subscription.id)
        if policy is None:
            snapshot = await self.purchased_ip.current(subscription.id)
            if snapshot is not None:
                policy = await asyncio.to_thread(
                    IpLimitChoice.model_validate_json, snapshot.policy_json
                )
        session = await self.sessions.by_ip(subscription.id, data.source_ip)
        if (
            session is not None
            and session.blocked_until is not None
            and session.blocked_until > now
        ):
            return IpAdmissionDecision(
                subscription.id,
                data.source_ip,
                False,
                "ip_blocked",
                session.blocked_until,
                session.blocked_until,
            )
        seconds = (
            policy.lease_seconds
            if policy
            else self.settings.ip_limits.lease_seconds
        )
        valid_until = min(
            now + timedelta(seconds=seconds),
            subscription.expires_at or now + timedelta(seconds=seconds),
        )
        if policy is None or not policy.enabled:
            await self._record_issued(state, valid_until)
            return IpAdmissionDecision(
                subscription.id,
                data.source_ip,
                True,
                "limit_disabled",
                valid_until,
            )
        if session is None or session.expires_at <= now:
            active = await self.sessions.active_sessions(
                subscription.id,
                now,
                policy.max_ips,
            )
            if len(active) >= policy.max_ips:
                blocked_until = now + timedelta(seconds=policy.ban_seconds)
                if policy.mode == "reject_new":
                    denied = IpSessionModel(
                        subscription_id=subscription.id,
                        source_ip=data.source_ip,
                        last_node_id=node.id,
                        first_seen_at=now,
                        last_seen_at=now,
                        expires_at=now,
                        blocked_until=blocked_until,
                        block_reason="ip_limit_exceeded",
                    )
                    if session is None:
                        await self.sessions.create(denied)
                    else:
                        await self.sessions.change(session, denied)
                    return IpAdmissionDecision(
                        subscription.id,
                        data.source_ip,
                        False,
                        "ip_limit_exceeded",
                        blocked_until,
                        blocked_until,
                    )
                oldest = min(
                    active, key=lambda item: (item.first_seen_at, item.id)
                )
                await self.sessions.change(
                    oldest,
                    IpSessionModel.patch(
                        expires_at=now,
                        blocked_until=blocked_until,
                        block_reason="replaced_oldest",
                        blocked_by_staff_id=None,
                    ),
                )
        changes = IpSessionModel(
            subscription_id=subscription.id,
            source_ip=data.source_ip,
            last_node_id=node.id,
            first_seen_at=session.first_seen_at
            if session and session.expires_at > now
            else now,
            last_seen_at=now,
            expires_at=valid_until,
            blocked_until=None,
            block_reason=None,
            blocked_by_staff_id=None,
        )
        if session is None:
            await self.sessions.create(changes)
        else:
            await self.sessions.change(session, changes)
        await self._record_issued(state, valid_until)
        return IpAdmissionDecision(
            subscription.id, data.source_ip, True, "ip_admitted", valid_until
        )

    async def _record_issued(
        self, state: IpLeaseStateModel, valid_until: datetime
    ) -> None:
        if state.issued_until is None or valid_until > state.issued_until:
            await self.lease_states.change(
                state, IpLeaseStateModel.patch(issued_until=valid_until)
            )


class IpRestrictionCommand:
    def __init__(
        self,
        subscriptions: SubscriptionRepository,
        sessions: IpSessionRepository,
        settings: PapilioSettings,
    ) -> None:
        self.subscriptions = subscriptions
        self.sessions = sessions
        self.settings = settings

    @transactional
    async def ban(
        self,
        subscription_id: int,
        session_id: int,
        data: IpManualBan,
        staff_id: int,
    ) -> IpSessionModel:
        subscription = await self.subscriptions.locked(subscription_id)
        if subscription is None:
            raise _missing("subscription", subscription_id)
        session = await self.sessions.get_by_id(session_id)
        if session is None or session.subscription_id != subscription_id:
            raise _missing("ip_session", session_id)
        if data.seconds > self.settings.ip_limits.max_ban_seconds:
            raise _conflict("ip_ban_capacity", subscription_id)
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        result = await self.sessions.change(
            session,
            IpSessionModel.patch(
                expires_at=now,
                blocked_until=now + timedelta(seconds=data.seconds),
                block_reason=data.reason,
                blocked_by_staff_id=staff_id,
            ),
        )
        return result

    @transactional
    async def unban(
        self, subscription_id: int, session_id: int
    ) -> IpSessionModel:
        subscription = await self.subscriptions.locked(subscription_id)
        if subscription is None:
            raise _missing("subscription", subscription_id)
        session = await self.sessions.get_by_id(session_id)
        if session is None or session.subscription_id != subscription_id:
            raise _missing("ip_session", session_id)
        result = await self.sessions.change(
            session,
            IpSessionModel.patch(
                expires_at=datetime.now(UTC).replace(
                    tzinfo=None, microsecond=0
                ),
                blocked_until=None,
                block_reason=None,
                blocked_by_staff_id=None,
            ),
        )
        return result


def _missing(entity: str, id: int) -> NotFoundException:
    return NotFoundException(
        message="رکورد پیدا نشد.",
        message_code=f"{entity}_not_found",
        entity=entity,
        identifier="id",
        identifier_value=id,
    )


def _conflict(code: str, subscription_id: int) -> ConflictException:
    return ConflictException(
        message="سیاست محدودیت یا رابطهٔ نود و اشتراک معتبر نیست.",
        message_code=code,
        unique_dict={"subscription_id": subscription_id},
    )
