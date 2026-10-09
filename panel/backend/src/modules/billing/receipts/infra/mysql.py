from typing import cast

from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import func, select
from sqlalchemy.orm import InstrumentedAttribute, defer
from sqlmodel import col

from src.modules.billing.receipts.domain.models import PaymentReceiptModel
from src.modules.billing.receipts.infra.tables import PaymentReceiptTable


class PaymentReceiptRepository(
    MySQLPersistenceRepository[PaymentReceiptModel]
):
    table = PaymentReceiptTable

    async def by_content(
        self, topup_id: int, content_hash: str
    ) -> PaymentReceiptModel | None:
        result = await self.uow.execute(
            select(PaymentReceiptTable)
            .where(
                col(PaymentReceiptTable.topup_id) == topup_id,
                col(PaymentReceiptTable.content_hash) == content_hash,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
            .options(
                defer(
                    cast(
                        InstrumentedAttribute[str],
                        PaymentReceiptTable.encrypted_payload,
                    )
                )
            )
        )
        return result.scalar_one_or_none()

    async def count(self, topup_id: int) -> int:
        result = await self.uow.execute(
            select(func.count())
            .select_from(PaymentReceiptTable)
            .where(col(PaymentReceiptTable.topup_id) == topup_id)
            .with_for_update()
        )
        return result.scalar_one()

    async def page(
        self, topup_id: int, offset: int, limit: int
    ) -> PagedType[PaymentReceiptModel]:
        query = (
            select(PaymentReceiptTable)
            .where(col(PaymentReceiptTable.topup_id) == topup_id)
            .order_by(col(PaymentReceiptTable.id).desc())
            .options(
                defer(
                    cast(
                        InstrumentedAttribute[str],
                        PaymentReceiptTable.encrypted_payload,
                    )
                )
            )
        )
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result
