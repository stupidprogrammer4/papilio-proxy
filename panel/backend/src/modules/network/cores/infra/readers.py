from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import select
from sqlmodel import col

from src.modules.network.configurations.infra.tables import ConfigurationTable
from src.modules.network.cores.domain.exports import CoreConfigurationRevision


class CoreConfigurationReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def configurations(
        self, core_id: int, limit: int
    ) -> list[CoreConfigurationRevision]:
        result = await self.uow.execute(
            select(ConfigurationTable)
            .where(col(ConfigurationTable.core_id) == core_id)
            .order_by(col(ConfigurationTable.id))
            .limit(limit)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        return [
            CoreConfigurationRevision(
                configuration_id=row.id, revision=row.revision
            )
            for row in result.scalars()
        ]
