from papilio.infra.db.uow import MySQLUnitOfWork
from papilio.schemas.results import PagedType
from sqlalchemy import func, select
from sqlmodel import col

from src.modules.network.core_runtime.domain.results import RuntimeRevisionOut
from src.modules.network.core_runtime.infra.tables import (
    CoreRuntimeRevisionTable,
)


class RuntimeRevisionMetadataReader:
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def page(
        self, core_id: int, offset: int, limit: int
    ) -> PagedType[RuntimeRevisionOut]:
        total = await self.uow.execute(
            select(func.count())
            .select_from(CoreRuntimeRevisionTable)
            .where(col(CoreRuntimeRevisionTable.core_id) == core_id)
        )
        rows = await self.uow.execute(
            select(
                col(CoreRuntimeRevisionTable.id),
                col(CoreRuntimeRevisionTable.core_id),
                col(CoreRuntimeRevisionTable.mode),
                col(CoreRuntimeRevisionTable.bundle_sha256),
                col(CoreRuntimeRevisionTable.membership_sha256),
                col(CoreRuntimeRevisionTable.usage_sha256),
                col(CoreRuntimeRevisionTable.artifact_count),
                col(CoreRuntimeRevisionTable.created_by_staff_id),
                col(CoreRuntimeRevisionTable.created_at),
            )
            .where(col(CoreRuntimeRevisionTable.core_id) == core_id)
            .order_by(col(CoreRuntimeRevisionTable.id).desc())
            .limit(limit)
            .offset(offset)
        )
        return PagedType(
            [RuntimeRevisionOut.model_validate(row._mapping) for row in rows],
            total.scalar_one(),
        )
