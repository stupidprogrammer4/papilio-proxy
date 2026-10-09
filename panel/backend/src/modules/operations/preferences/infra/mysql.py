from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import func, select
from sqlmodel import col

from src.modules.operations.preferences.domain.models import (
    PreferencesRevisionModel,
)
from src.modules.operations.preferences.infra.tables import (
    PreferencesRevisionTable,
)


class PreferencesRepository(
    MySQLPersistenceRepository[PreferencesRevisionModel]
):
    table = PreferencesRevisionTable

    async def latest(
        self, *, locked: bool = False
    ) -> PreferencesRevisionModel | None:
        if locked:
            # Current locking read; MAX subqueries can retain an old RR view.
            query = (
                select(PreferencesRevisionTable)
                .order_by(col(PreferencesRevisionTable.revision).desc())
                .limit(1)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        else:
            query = select(PreferencesRevisionTable).where(
                col(PreferencesRevisionTable.revision)
                == select(
                    func.max(col(PreferencesRevisionTable.revision))
                ).scalar_subquery()
            )
        result = await self.uow.execute(query)
        return result.scalar_one_or_none()

    async def page(
        self, offset: int, limit: int
    ) -> PagedType[PreferencesRevisionModel]:
        query = select(PreferencesRevisionTable).order_by(
            col(PreferencesRevisionTable.revision).desc()
        )
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result
