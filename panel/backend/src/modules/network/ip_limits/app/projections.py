from datetime import UTC

from papilio.errors.exceptions import ConflictException, NotFoundException

from src.config.settings import PapilioSettings
from src.modules.network.ip_limits.domain.dtos import IpLimitChoice
from src.modules.network.ip_limits.domain.purchased import (
    EffectiveIpPolicyRead,
    IpPolicyTransitionRead,
    PurchasedIpPolicyRead,
    SubscriptionIpPolicyRead,
)
from src.modules.network.ip_limits.infra.projections import (
    IpPolicyProjectionFacts,
    IpPolicyProjectionReader,
)


def _projection(facts: IpPolicyProjectionFacts) -> SubscriptionIpPolicyRead:
    purchased = None
    if facts.policy_json is not None:
        assert facts.captured_at is not None
        purchased = PurchasedIpPolicyRead.model_validate(
            {
                "policy": IpLimitChoice.model_validate_json(facts.policy_json),
                "source": facts.source,
                "plan_id": facts.plan_id,
                "captured_at": facts.captured_at.replace(tzinfo=UTC),
            }
        )
    if facts.enabled is not None:
        effective = EffectiveIpPolicyRead(
            policy=IpLimitChoice.model_validate(
                {
                    "enabled": facts.enabled,
                    "max_ips": facts.max_ips,
                    "lease_seconds": facts.lease_seconds,
                    "ban_seconds": facts.ban_seconds,
                    "mode": facts.mode,
                }
            ),
            source="subscription_override",
        )
    elif purchased is not None:
        effective = EffectiveIpPolicyRead(
            policy=purchased.policy, source="purchased_snapshot"
        )
    else:
        effective = EffectiveIpPolicyRead(
            policy=None, source="legacy_unrestricted"
        )
    if facts.pending_policy_json is not None:
        transition = IpPolicyTransitionRead.model_validate(
            {
                "status": "blocked" if facts.blocked_reason else "draining",
                "target_policy": IpLimitChoice.model_validate_json(
                    facts.pending_policy_json
                ),
                "mode": facts.transition_mode,
                "retry_at": facts.drain_until.replace(tzinfo=UTC)
                if facts.drain_until is not None
                else None,
                "reason": facts.blocked_reason or "ip_policy_draining",
            }
        )
        effective = EffectiveIpPolicyRead.model_validate(
            {
                "policy": IpLimitChoice.model_validate_json(
                    facts.previous_policy_json
                )
                if facts.previous_policy_json is not None
                else None,
                "source": facts.previous_source,
                "transition": transition,
            }
        )
    return SubscriptionIpPolicyRead(
        purchased_ip_policy=purchased, effective_ip_policy=effective
    )


class IpPolicyProjectionQuery:
    def __init__(
        self, reader: IpPolicyProjectionReader, settings: PapilioSettings
    ) -> None:
        self.reader, self.settings = reader, settings

    async def single(self, id: int) -> SubscriptionIpPolicyRead:
        facts = await self.reader.single(id)
        if facts is None:
            raise NotFoundException(
                message="Subscription was not found.",
                message_code="subscription_not_found",
                entity="subscription",
                identifier="id",
                identifier_value=id,
            )
        return _projection(facts)

    async def many(
        self, ids: list[int]
    ) -> dict[int, SubscriptionIpPolicyRead]:
        unique = sorted(set(ids))
        capacity = self.settings.operations.admin_page_size_max
        if len(unique) > capacity:
            raise ConflictException(
                message="IP projection exceeds application capacity.",
                message_code="ip_projection_capacity",
                unique_dict={"requested": len(unique)},
            )
        if not unique:
            return {}
        facts = await self.reader.many(unique, capacity)
        return {row.subscription_id: _projection(row) for row in facts}
