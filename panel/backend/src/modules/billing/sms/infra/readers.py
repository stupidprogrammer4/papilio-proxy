from datetime import datetime

from papilio.infra.db.tools.read import fetch_page
from papilio.infra.db.uow import MySQLUnitOfWork
from papilio.schemas.results import PagedType
from sqlalchemy import exists, select
from sqlmodel import col

from src.modules.billing.sms.domain.models import SmsEventModel
from src.modules.billing.sms.infra.tables import SmsEventTable
from src.modules.billing.wallet.infra.tables import TopupTable


class SmsCandidateReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def for_topup(
        self,
        amount_rial: int,
        since: datetime,
        until: datetime,
        offset: int,
        limit: int,
        settled_status: str,
    ) -> PagedType[SmsEventModel]:
        used_reference = exists(
            select(col(TopupTable.id)).where(
                col(TopupTable.status) == settled_status,
                col(TopupTable.bank_reference)
                == col(SmsEventTable.bank_reference),
            )
        )
        query = (
            select(SmsEventTable)
            .where(
                col(SmsEventTable.amount_rial) == amount_rial,
                col(SmsEventTable.sent_at) >= since,
                col(SmsEventTable.sent_at) <= until,
                col(SmsEventTable.bank_reference).is_not(None),
                ~used_reference,
            )
            .order_by(col(SmsEventTable.sent_at).desc())
        )
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result
