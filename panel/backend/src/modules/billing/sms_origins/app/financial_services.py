from src.modules.billing.sms_origins.domain.models import (
    SmsSettlementClaimModel,
    SmsSettlementDecisionModel,
    SmsSettlementModel,
)
from src.modules.billing.sms_origins.infra.mysql import (
    SmsSettlementClaimRepository,
    SmsSettlementDecisionRepository,
    SmsSettlementRepository,
)


class SmsSettlementService:
    """Immutable proof records; the owning command chooses all evidence."""

    def __init__(self, repo: SmsSettlementRepository) -> None:
        self.repo = repo

    async def by_event(self, event_id: int) -> SmsSettlementModel | None:
        result = await self.repo.by_event(event_id)
        return result

    async def create(self, data: SmsSettlementModel) -> SmsSettlementModel:
        result = await self.repo.create(data)
        return result


class SmsSettlementClaimService:
    """Current identity facts under financial admission."""

    def __init__(self, repo: SmsSettlementClaimRepository) -> None:
        self.repo = repo

    async def current_many(
        self, keys: list[tuple[str, str]]
    ) -> list[SmsSettlementClaimModel]:
        if not keys:
            return []
        result = await self.repo.current_many(sorted(set(keys)))
        return result

    async def create_many(
        self, settlement_id: int, keys: list[tuple[str, str]]
    ) -> None:
        if keys:
            await self.repo.create_many(settlement_id, sorted(set(keys)))


class SmsSettlementDecisionService:
    """Current settlement decisions, distinct from parser observations."""

    def __init__(self, repo: SmsSettlementDecisionRepository) -> None:
        self.repo = repo

    async def get(self, event_id: int) -> SmsSettlementDecisionModel | None:
        result = await self.repo.find(event_id)
        return result

    async def record(
        self, data: SmsSettlementDecisionModel
    ) -> SmsSettlementDecisionModel:
        current = await self.repo.by_event(data.sms_event_id)
        if current is None:
            result = await self.repo.create(data)
        else:
            result = await self.repo.change(
                current,
                SmsSettlementDecisionModel.patch(
                    status=data.status,
                    reason_code=data.reason_code,
                    checked_at=data.checked_at,
                    candidate_count=data.candidate_count,
                    topup_id=data.topup_id,
                    settlement_id=data.settlement_id,
                ),
            )
        return result
