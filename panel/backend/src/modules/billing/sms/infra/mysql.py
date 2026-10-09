from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import select
from sqlmodel import col

from src.modules.billing.sms.domain.models import SmsEventModel
from src.modules.billing.sms.infra.tables import SmsEventTable


class SmsRepository(MySQLPersistenceRepository[SmsEventModel]):
    table = SmsEventTable

    async def by_event_id(self, event_id: str) -> SmsEventModel | None:
        result = await self.uow.execute(
            select(SmsEventTable).where(
                col(SmsEventTable.event_id) == event_id
            )
        )
        return result.scalar_one_or_none()

    async def page(self, offset: int, limit: int) -> PagedType[SmsEventModel]:
        query = select(SmsEventTable).order_by(col(SmsEventTable.id).desc())
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result
