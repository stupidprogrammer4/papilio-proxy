from dataclasses import dataclass
from datetime import datetime

from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import select
from sqlmodel import col

from src.modules.network.ip_limits.infra.tables import (
    IpLeaseStateTable,
    IpLimitPolicyTable,
    PurchasedIpPolicyTable,
)
from src.modules.sales.subscriptions.infra.tables import SubscriptionTable


@dataclass(frozen=True, slots=True)
class IpPolicyProjectionFacts:
    subscription_id: int
    policy_json: str | None
    source: str | None
    plan_id: int | None
    captured_at: datetime | None
    enabled: bool | None
    max_ips: int | None
    lease_seconds: int | None
    ban_seconds: int | None
    mode: str | None
    pending_policy_json: str | None
    previous_policy_json: str | None
    previous_source: str | None
    transition_mode: str | None
    drain_until: datetime | None
    blocked_reason: str | None


def _statement():
    snapshot, override, subscription = (
        PurchasedIpPolicyTable,
        IpLimitPolicyTable,
        SubscriptionTable,
    )
    return (
        select(
            col(subscription.id).label("subscription_id"),
            col(snapshot.policy_json),
            col(snapshot.source),
            col(snapshot.plan_id),
            col(snapshot.created_at).label("captured_at"),
            col(override.enabled),
            col(override.max_ips),
            col(override.lease_seconds),
            col(override.ban_seconds),
            col(override.mode),
            col(IpLeaseStateTable.pending_policy_json),
            col(IpLeaseStateTable.previous_policy_json),
            col(IpLeaseStateTable.previous_source),
            col(IpLeaseStateTable.transition_mode),
            col(IpLeaseStateTable.drain_until),
            col(IpLeaseStateTable.blocked_reason),
        )
        .select_from(subscription)
        .outerjoin(
            snapshot, col(snapshot.subscription_id) == col(subscription.id)
        )
        .outerjoin(
            override, col(override.subscription_id) == col(subscription.id)
        )
        .outerjoin(
            IpLeaseStateTable,
            col(IpLeaseStateTable.subscription_id) == col(subscription.id),
        )
    )


class IpPolicyProjectionReader:
    """Declared purchased snapshot and operational override read model."""

    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def single(self, id: int) -> IpPolicyProjectionFacts | None:
        result = await self.uow.execute(
            _statement().where(col(SubscriptionTable.id) == id)
        )
        row = result.one_or_none()
        return (
            IpPolicyProjectionFacts(**row._mapping)
            if row is not None
            else None
        )

    async def many(
        self, ids: list[int], limit: int
    ) -> list[IpPolicyProjectionFacts]:
        result = await self.uow.execute(
            _statement()
            .where(col(SubscriptionTable.id).in_(ids))
            .order_by(col(SubscriptionTable.id))
            .limit(limit)
        )
        return [IpPolicyProjectionFacts(**row._mapping) for row in result]
