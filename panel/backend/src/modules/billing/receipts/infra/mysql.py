from typing import cast
from uuid import uuid4

from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import InstrumentedAttribute, defer
from sqlmodel import col

from src.modules.billing.receipts.domain.models import PaymentReceiptModel
from src.modules.billing.receipts.domain.outbox import ReceiptOcrOutboxClaim
from src.modules.billing.receipts.domain.outbox_models import (
    ReceiptOcrOutboxModel,
)
from src.modules.billing.receipts.infra.outbox_tables import (
    ReceiptOcrOutboxTable,
)
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

    async def store_extraction(
        self, id: int, ciphertext: str, status: str
    ) -> None:
        await self.uow.execute(
            update(PaymentReceiptTable)
            .where(
                col(PaymentReceiptTable.id) == id,
                col(PaymentReceiptTable.encrypted_extraction).is_(None),
            )
            .values(encrypted_extraction=ciphertext, ocr_status=status)
        )

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


class PaymentReceiptOutboxRepository(
    MySQLPersistenceRepository[ReceiptOcrOutboxModel]
):
    table = ReceiptOcrOutboxTable

    async def ensure_pending(self, receipt_id: int) -> None:
        await self.uow.execute(
            insert(self.table)
            .values(receipt_id=receipt_id, status="pending")
            .prefix_with("IGNORE")
        )

    async def claim_next(self) -> ReceiptOcrOutboxClaim | None:
        eligible = or_(
            col(self.table.status) == "pending",
            and_(
                col(self.table.status) == "processing",
                col(self.table.lease_until) <= func.utc_timestamp(),
            ),
        )
        result = await self.uow.execute(
            select(self.table)
            .where(eligible)
            .order_by(col(self.table.id))
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        claim_token = uuid4().hex
        await self.uow.execute(
            update(self.table)
            .where(col(self.table.id) == row.id)
            .values(
                status="processing",
                attempts=col(self.table.attempts) + 1,
                claim_token=claim_token,
                lease_until=func.timestampadd(
                    text("SECOND"), 120, func.utc_timestamp()
                ),
            )
        )
        return ReceiptOcrOutboxClaim(
            outbox_id=row.id,
            receipt_id=row.receipt_id,
            claim_token=claim_token,
        )

    async def mark_published(self, outbox_id: int, claim_token: str) -> bool:
        result = await self.uow.execute(
            update(self.table)
            .where(
                col(self.table.id) == outbox_id,
                col(self.table.status) == "processing",
                col(self.table.claim_token) == claim_token,
            )
            .values(
                status="published",
                claim_token=None,
                lease_until=None,
                published_at=func.utc_timestamp(),
            )
        )
        changed = cast(CursorResult[object], result).rowcount
        return changed == 1
