from datetime import datetime

from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import func, select


class IpAdmissionClock:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def now(self) -> datetime:
        result = await self.uow.execute(select(func.utc_timestamp(6)))
        return result.scalar_one()
