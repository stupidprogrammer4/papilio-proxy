from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert
from sqlmodel import col

from src.modules.operations.automation.domain.models import (
    AutomationRegistrationModel,
    AutomationRevisionModel,
)
from src.modules.operations.automation.infra.tables import (
    AutomationRegistrationTable,
    AutomationRevisionTable,
)


class AutomationRegistrationRepository(
    MySQLPersistenceRepository[AutomationRegistrationModel]
):
    table = AutomationRegistrationTable

    async def ensure_default(self, model: AutomationRegistrationModel) -> None:
        await self.uow.execute(
            insert(self.table)
            .values(**model.model_dump(exclude_unset=True))
            .prefix_with("IGNORE")
        )

    async def by_key(self, key: str) -> AutomationRegistrationModel | None:
        result = await self.uow.execute(
            select(self.table).where(col(self.table.key) == key)
        )
        return result.scalar_one_or_none()

    async def locked(self, key: str) -> AutomationRegistrationModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.key) == key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def configured(
        self, keys: list[str]
    ) -> list[AutomationRegistrationModel]:
        result = await self.uow.execute(
            select(self.table).where(col(self.table.key).in_(keys))
        )
        return list(result.scalars().all())


class AutomationRevisionRepository(
    MySQLPersistenceRepository[AutomationRevisionModel]
):
    table = AutomationRevisionTable

    async def page(
        self, key: str, offset: int, limit: int
    ) -> PagedType[AutomationRevisionModel]:
        query = (
            select(self.table)
            .where(col(self.table.key) == key)
            .order_by(col(self.table.revision).desc())
        )
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result
