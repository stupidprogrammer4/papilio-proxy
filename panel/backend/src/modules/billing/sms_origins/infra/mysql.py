from datetime import datetime

from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import func, insert, select, tuple_
from sqlmodel import col

from src.modules.billing.sms_origins.domain.models import (
    ReceivingAliasModel,
    ReceivingRealmModel,
    SmsOriginAdmissionModel,
    SmsParserProfileModel,
    SmsParserRevisionModel,
    SmsSettlementClaimModel,
    SmsSettlementDecisionModel,
    SmsSettlementModel,
)
from src.modules.billing.sms_origins.infra.tables import (
    ReceivingAliasTable,
    ReceivingRealmTable,
    SmsOriginAdmissionTable,
    SmsParserProfileTable,
    SmsParserRevisionTable,
    SmsSettlementClaimTable,
    SmsSettlementDecisionTable,
    SmsSettlementTable,
)


class ReceivingRealmRepository(
    MySQLPersistenceRepository[ReceivingRealmModel]
):
    table = ReceivingRealmTable

    async def utc_now(self) -> datetime:
        result = await self.uow.execute(select(func.utc_timestamp(6)))
        return result.scalar_one()

    async def locked(self, id: int) -> ReceivingRealmModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def change(
        self, row: ReceivingRealmModel, changes: ReceivingRealmModel
    ) -> ReceivingRealmModel:
        await self.update_row_by_id(row.id, changes)
        await self.uow.refresh(row)
        return row

    async def admission_ids(self, limit: int) -> list[int]:
        result = await self.uow.execute(
            select(col(self.table.id))
            .order_by(col(self.table.id))
            .limit(limit)
            .with_for_update(read=True)
        )
        return list(result.scalars())

    async def page(
        self, q: str | None, offset: int, limit: int
    ) -> PagedType[ReceivingRealmModel]:
        query = select(self.table).order_by(col(self.table.id).desc())
        if q is not None:
            query = query.where(
                col(self.table.title).contains(q, autoescape=True)
            )
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result


class ReceivingAliasRepository(
    MySQLPersistenceRepository[ReceivingAliasModel]
):
    table = ReceivingAliasTable

    async def locked(self, id: int) -> ReceivingAliasModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def change(
        self, row: ReceivingAliasModel, changes: ReceivingAliasModel
    ) -> ReceivingAliasModel:
        await self.update_row_by_id(row.id, changes)
        await self.uow.refresh(row)
        return row

    async def by_account(self, digest: str) -> ReceivingAliasModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.account_sha256) == digest)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def admission_ids(self, realm_id: int, limit: int) -> list[int]:
        result = await self.uow.execute(
            select(col(self.table.id))
            .where(col(self.table.realm_id) == realm_id)
            .order_by(col(self.table.id))
            .limit(limit)
            .with_for_update(read=True)
        )
        return list(result.scalars())

    async def page(
        self, realm_id: int, offset: int, limit: int
    ) -> PagedType[ReceivingAliasModel]:
        query = (
            select(self.table)
            .where(col(self.table.realm_id) == realm_id)
            .order_by(col(self.table.id))
        )
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result


class SmsParserProfileRepository(
    MySQLPersistenceRepository[SmsParserProfileModel]
):
    table = SmsParserProfileTable

    async def locked(self, id: int) -> SmsParserProfileModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def change(
        self, row: SmsParserProfileModel, changes: SmsParserProfileModel
    ) -> SmsParserProfileModel:
        await self.update_row_by_id(row.id, changes)
        await self.uow.refresh(row)
        return row

    async def admission_ids(self, limit: int) -> list[int]:
        result = await self.uow.execute(
            select(col(self.table.id))
            .order_by(col(self.table.id))
            .limit(limit)
            .with_for_update(read=True)
        )
        return list(result.scalars())

    async def page(
        self, q: str | None, offset: int, limit: int
    ) -> PagedType[SmsParserProfileModel]:
        query = select(self.table).order_by(col(self.table.id).desc())
        if q is not None:
            query = query.where(
                col(self.table.title).contains(q, autoescape=True)
            )
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result


class SmsParserRevisionRepository(
    MySQLPersistenceRepository[SmsParserRevisionModel]
):
    table = SmsParserRevisionTable

    async def locked(self, id: int) -> SmsParserRevisionModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def change(
        self, row: SmsParserRevisionModel, changes: SmsParserRevisionModel
    ) -> SmsParserRevisionModel:
        await self.update_row_by_id(row.id, changes)
        await self.uow.refresh(row)
        return row

    async def current(
        self, profile_id: int, revision: int
    ) -> SmsParserRevisionModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(
                col(self.table.profile_id) == profile_id,
                col(self.table.revision) == revision,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def page(
        self, profile_id: int, offset: int, limit: int
    ) -> PagedType[SmsParserRevisionModel]:
        query = (
            select(self.table)
            .where(col(self.table.profile_id) == profile_id)
            .order_by(col(self.table.revision).desc())
        )
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result


class SmsSettlementRepository(MySQLPersistenceRepository[SmsSettlementModel]):
    table = SmsSettlementTable

    async def locked(self, id: int) -> SmsSettlementModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def change(
        self, row: SmsSettlementModel, changes: SmsSettlementModel
    ) -> SmsSettlementModel:
        await self.update_row_by_id(row.id, changes)
        await self.uow.refresh(row)
        return row

    async def by_event(self, sms_id: int) -> SmsSettlementModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.sms_event_id) == sms_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()


class SmsSettlementClaimRepository(
    MySQLPersistenceRepository[SmsSettlementClaimModel]
):
    table = SmsSettlementClaimTable

    async def locked(self, id: int) -> SmsSettlementClaimModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def change(
        self, row: SmsSettlementClaimModel, changes: SmsSettlementClaimModel
    ) -> SmsSettlementClaimModel:
        await self.update_row_by_id(row.id, changes)
        await self.uow.refresh(row)
        return row

    async def by_identity(
        self, kind: str, key: str
    ) -> SmsSettlementClaimModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(
                col(self.table.identity_kind) == kind,
                col(self.table.identity_key) == key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def current_many(
        self, keys: list[tuple[str, str]]
    ) -> list[SmsSettlementClaimModel]:
        result = await self.uow.execute(
            select(self.table)
            .where(
                tuple_(
                    col(self.table.identity_kind), col(self.table.identity_key)
                ).in_(keys)
            )
            .order_by(
                col(self.table.identity_kind), col(self.table.identity_key)
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars())

    async def create_many(
        self, settlement_id: int, keys: list[tuple[str, str]]
    ) -> None:
        await self.uow.execute(
            insert(self.table).values(
                [
                    {
                        "settlement_id": settlement_id,
                        "identity_kind": kind,
                        "identity_key": key,
                    }
                    for kind, key in keys
                ]
            )
        )
        await self.uow.flush()


class SmsOriginAdmissionRepository(
    MySQLPersistenceRepository[SmsOriginAdmissionModel]
):
    table = SmsOriginAdmissionTable

    async def locked(self, key: str) -> SmsOriginAdmissionModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.key) == key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()


class SmsSettlementDecisionRepository(
    MySQLPersistenceRepository[SmsSettlementDecisionModel]
):
    table = SmsSettlementDecisionTable

    async def by_event(self, id: int) -> SmsSettlementDecisionModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.sms_event_id) == id)
            .order_by(col(self.table.id).desc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalars().first()

    async def find(self, id: int) -> SmsSettlementDecisionModel | None:
        result = await self.uow.execute(
            select(self.table)
            .where(col(self.table.sms_event_id) == id)
            .order_by(col(self.table.id).desc())
        )
        return result.scalars().first()
