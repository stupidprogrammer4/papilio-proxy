from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from sqlalchemy import select
from sqlmodel import col

from src.modules.billing.reviews.domain.models import PaymentReviewModel
from src.modules.billing.reviews.infra.tables import PaymentReviewTable


class PaymentReviewRepository(MySQLPersistenceRepository[PaymentReviewModel]):
    table = PaymentReviewTable

    async def store(self, data: PaymentReviewModel) -> PaymentReviewModel:
        result = await self.uow.execute(
            select(PaymentReviewTable).where(
                col(PaymentReviewTable.topup_id) == data.topup_id
            )
        )
        stored = result.scalar_one_or_none()
        if stored is None:
            created = await self.create(data)
            return created
        await self.update_row_by_id(stored.id, data)
        await self.uow.refresh(stored)
        return stored
