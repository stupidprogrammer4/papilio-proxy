from src.modules.sales.checkout.app.errors import checkout_conflict
from src.modules.sales.checkout.domain.attempts import CheckoutAttemptModel
from src.modules.sales.checkout.infra.attempts import CheckoutAttemptRepository


class CheckoutAttemptService:
    def __init__(self, repo: CheckoutAttemptRepository) -> None:
        self.repo = repo

    async def reserve(
        self, customer_id: int, key: str, digest: str | None
    ) -> CheckoutAttemptModel:
        row = await self.repo.reserve(
            CheckoutAttemptModel(
                customer_id=customer_id,
                request_key=key,
                body_sha256=digest,
            )
        )
        if row.customer_id != customer_id:
            raise checkout_conflict("checkout_request_conflict", row.id)
        return row

    @staticmethod
    def admit(row: CheckoutAttemptModel, digest: str) -> None:
        if row.retired:
            raise checkout_conflict("checkout_attempt_retired", row.id)
        if row.body_sha256 != digest:
            raise checkout_conflict("checkout_request_conflict", row.id)

    async def link(
        self, row: CheckoutAttemptModel, intent_id: int, digest: str
    ) -> None:
        if row.intent_id is not None and row.intent_id != intent_id:
            raise checkout_conflict("checkout_request_conflict", row.id)
        await self.repo.change_existing(
            row,
            CheckoutAttemptModel.patch(
                intent_id=intent_id,
                body_sha256=digest,
            ),
        )

    async def retire(self, row: CheckoutAttemptModel) -> None:
        await self.repo.change_existing(
            row, CheckoutAttemptModel.patch(retired=True)
        )
