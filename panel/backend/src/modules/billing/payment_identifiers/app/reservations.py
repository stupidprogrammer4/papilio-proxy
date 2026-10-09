from src.modules.billing.payment_identifiers.domain.models import (
    PaymentAmountReservationModel,
)
from src.modules.billing.payment_identifiers.infra.mysql import (
    PaymentAmountReservationRepository,
)


class PaymentAmountReservationService:
    def __init__(self, repo: PaymentAmountReservationRepository) -> None:
        self.repo = repo

    async def create(
        self, data: PaymentAmountReservationModel
    ) -> PaymentAmountReservationModel:
        result = await self.repo.create(data)
        return result
