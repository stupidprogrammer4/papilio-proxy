from papilio.infra.db.tools.decorators import transactional

from src.modules.billing.receipts.app.outbox_interfaces import (
    IReceiptOcrEventPublisher,
)
from src.modules.billing.receipts.domain.outbox import ReceiptOcrOutboxClaim
from src.modules.billing.receipts.infra.mysql import (
    PaymentReceiptOutboxRepository,
)


class PaymentReceiptOutboxCommand:
    def __init__(
        self,
        repo: PaymentReceiptOutboxRepository,
        publisher: IReceiptOcrEventPublisher,
    ) -> None:
        self.repo = repo
        self.publisher = publisher

    async def publish_next(self) -> bool:
        claim = await self._claim()
        if claim is None:
            return False
        await self.publisher.publish(claim.receipt_id)
        published = await self._mark_published(claim)
        return published

    @transactional
    async def _claim(self) -> ReceiptOcrOutboxClaim | None:
        claim = await self.repo.claim_next()
        return claim

    @transactional
    async def _mark_published(self, claim: ReceiptOcrOutboxClaim) -> bool:
        published = await self.repo.mark_published(
            claim.outbox_id, claim.claim_token
        )
        return published
