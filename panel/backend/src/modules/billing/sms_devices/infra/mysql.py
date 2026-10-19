from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import select
from sqlmodel import col

from src.modules.billing.sms_devices.domain.models import SmsDeviceModel
from src.modules.billing.sms_devices.infra.tables import SmsDeviceTable


class SmsDeviceRepository(MySQLPersistenceRepository[SmsDeviceModel]):
    table = SmsDeviceTable

    async def locked(self, id: int) -> SmsDeviceModel | None:
        result = await self.uow.execute(
            select(SmsDeviceTable)
            .where(col(SmsDeviceTable.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def change(
        self, row: SmsDeviceModel, data: SmsDeviceModel
    ) -> SmsDeviceModel:
        await self.update_row_by_id(row.id, data)
        await self.uow.refresh(row)
        return row

    async def report_status(
        self, row: SmsDeviceModel, data: SmsDeviceModel
    ) -> SmsDeviceModel:
        await self.update_row_by_id(row.id, data)
        await self.uow.refresh(row)
        return row

    async def page(
        self, offset: int, limit: int, q: str | None
    ) -> PagedType[SmsDeviceModel]:
        statement = select(SmsDeviceTable).order_by(
            col(SmsDeviceTable.id).desc()
        )
        if q:
            statement = statement.where(
                col(SmsDeviceTable.label).contains(q, autoescape=True)
            )
        result = await fetch_page(
            self.uow,
            statement,
            offset=offset,
            limit=limit,
        )
        return result
