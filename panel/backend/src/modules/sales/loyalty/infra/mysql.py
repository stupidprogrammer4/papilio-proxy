from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import select
from sqlmodel import col

from src.modules.sales.loyalty.domain.models import (
    CustomerTierModel,
    LoyaltyPolicyModel,
    PurchaseVolumeModel,
)
from src.modules.sales.loyalty.infra.tables import (
    CustomerTierTable,
    LoyaltyPolicyTable,
    PurchaseVolumeTable,
)


class CustomerTierRepository(MySQLPersistenceRepository[CustomerTierModel]):
    table = CustomerTierTable

    async def page(
        self, offset: int, limit: int
    ) -> PagedType[CustomerTierModel]:
        result = await fetch_page(
            self.uow,
            select(CustomerTierTable).order_by(
                CustomerTierTable.__table__.c.minimum_bytes,
                col(CustomerTierTable.id),
            ),
            offset=offset,
            limit=limit,
        )
        return result

    async def candidates_current(self, limit: int) -> list[CustomerTierModel]:
        result = await self.uow.execute(
            select(CustomerTierTable)
            .order_by(col(CustomerTierTable.id))
            .limit(limit)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def seed_missing(self, rows: list[CustomerTierModel]) -> None:
        await self.bulk_upsert(
            rows,
            insert_columns={
                "code": CustomerTierTable.__table__.c.code,
                "title": CustomerTierTable.__table__.c.title,
                "minimum_bytes": CustomerTierTable.__table__.c.minimum_bytes,
                "discount_bps": CustomerTierTable.__table__.c.discount_bps,
                "is_enabled": CustomerTierTable.__table__.c.is_enabled,
                "revision": CustomerTierTable.__table__.c.revision,
            },
            update_columns=[CustomerTierTable.__table__.c.code],
        )

    async def locked(self, id: int) -> CustomerTierModel | None:
        result = await self.uow.execute(
            select(CustomerTierTable)
            .where(col(CustomerTierTable.id) == id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def change(
        self, row: CustomerTierModel, changes: CustomerTierModel
    ) -> CustomerTierModel:
        await self.update_row_by_id(row.id, changes)
        await self.uow.refresh(row)
        return row


class LoyaltyPolicyRepository(MySQLPersistenceRepository[LoyaltyPolicyModel]):
    table = LoyaltyPolicyTable

    async def seed_missing(self, row: LoyaltyPolicyModel) -> None:
        await self.upsert(
            row, update_columns=[LoyaltyPolicyTable.__table__.c.code]
        )

    async def current(
        self, code: str, locked: bool
    ) -> LoyaltyPolicyModel | None:
        query = select(LoyaltyPolicyTable).where(
            col(LoyaltyPolicyTable.code) == code
        )
        if locked:
            query = query.with_for_update().execution_options(
                populate_existing=True
            )
        result = await self.uow.execute(query)
        return result.scalar_one_or_none()

    async def change(
        self, row: LoyaltyPolicyModel, changes: LoyaltyPolicyModel
    ) -> LoyaltyPolicyModel:
        await self.update_row_by_id(row.id, changes)
        await self.uow.refresh(row)
        return row


class PurchaseVolumeRepository(
    MySQLPersistenceRepository[PurchaseVolumeModel]
):
    table = PurchaseVolumeTable

    async def by_reference(self, reference: str) -> PurchaseVolumeModel | None:
        result = await self.uow.execute(
            select(PurchaseVolumeTable).where(
                col(PurchaseVolumeTable.reference) == reference
            )
        )
        return result.scalar_one_or_none()
