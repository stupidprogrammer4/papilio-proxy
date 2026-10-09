from typing import Literal

from papilio.errors.exceptions import ConflictException

from src.modules.network.ip_limits.domain.dtos import IpLimitChoice
from src.modules.network.ip_limits.domain.models import PurchasedIpPolicyModel
from src.modules.network.ip_limits.infra.purchased import (
    PurchasedIpPolicyRepository,
)


class PurchasedIpPolicyService:
    """One repository; captured terms cannot be rewritten by an override."""

    def __init__(self, repo: PurchasedIpPolicyRepository) -> None:
        self.repo = repo

    async def find(self, id: int) -> PurchasedIpPolicyModel | None:
        result = await self.repo.find(id)
        return result

    async def current(self, id: int) -> PurchasedIpPolicyModel | None:
        result = await self.repo.current(id)
        return result

    async def capture(
        self,
        subscription_id: int,
        plan_id: int | None,
        policy: IpLimitChoice,
        source: Literal["plan_override", "purchase_defaults"],
    ) -> PurchasedIpPolicyModel:
        existing = await self.repo.current(subscription_id)
        if existing is not None:
            if (
                existing.plan_id != plan_id
                or existing.source != source
                or IpLimitChoice.model_validate_json(existing.policy_json)
                != policy
            ):
                raise ConflictException(
                    message="Purchased IP terms cannot be replaced.",
                    message_code="purchased_ip_policy_immutable",
                    unique_dict={"subscription_id": subscription_id},
                )
            return existing
        result = await self.repo.create(
            PurchasedIpPolicyModel(
                subscription_id=subscription_id,
                plan_id=plan_id,
                source=source,
                policy_json=policy.model_dump_json(),
            )
        )
        return result
