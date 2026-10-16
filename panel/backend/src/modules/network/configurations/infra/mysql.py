from papilio.infra.db.repositories.backends.mysql import (
    MySQLPersistenceRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.schemas.results import PagedType
from sqlalchemy import select, update
from sqlmodel import col

from src.modules.network.configurations.domain.models import (
    ConfigurationJsonRevisionModel,
    ConfigurationModel,
    InboundPortModel,
    OpenVpnSocketModel,
    ProfileModel,
    SubscriptionLinkModel,
)
from src.modules.network.configurations.domain.results import (
    ProfileAppliedUpdate,
)
from src.modules.network.configurations.infra.tables import (
    ConfigurationJsonRevisionTable,
    ConfigurationTable,
    InboundPortTable,
    OpenVpnSocketTable,
    ProfileTable,
    SubscriptionLinkTable,
)


class ConfigurationRepository(MySQLPersistenceRepository[ConfigurationModel]):
    table = ConfigurationTable

    async def locked(self, id: int) -> ConfigurationModel | None:
        result = await self.uow.execute(
            select(ConfigurationTable)
            .where(col(ConfigurationTable.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def locked_many(self, ids: list[int]) -> list[ConfigurationModel]:
        result = await self.uow.execute(
            select(ConfigurationTable)
            .where(col(ConfigurationTable.id).in_(ids))
            .order_by(col(ConfigurationTable.id))
            .with_for_update()
        )
        return list(result.scalars().all())

    async def update_existing(
        self, existing: ConfigurationModel, changes: ConfigurationModel
    ) -> ConfigurationModel:
        await self.update_row_by_id(existing.id, changes)
        await self.uow.refresh(existing)
        return existing

    async def page(
        self, node_id: int | None, core_id: int | None, offset: int, limit: int
    ) -> PagedType[ConfigurationModel]:
        query = select(ConfigurationTable).order_by(
            col(ConfigurationTable.id).desc()
        )
        if node_id is not None:
            query = query.where(col(ConfigurationTable.node_id) == node_id)
        if core_id is not None:
            query = query.where(col(ConfigurationTable.core_id) == core_id)
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result


class OpenVpnSocketRepository(MySQLPersistenceRepository[OpenVpnSocketModel]):
    table = OpenVpnSocketTable

    async def by_configuration(
        self, configuration_id: int, lock: bool
    ) -> OpenVpnSocketModel | None:
        query = (
            select(OpenVpnSocketTable)
            .where(
                col(OpenVpnSocketTable.configuration_id) == configuration_id
            )
            .execution_options(populate_existing=True)
        )
        if lock:
            query = query.with_for_update()
        result = await self.uow.execute(query)
        return result.scalar_one_or_none()

    async def update_existing(
        self, existing: OpenVpnSocketModel, changes: OpenVpnSocketModel
    ) -> OpenVpnSocketModel:
        await self.update_row_by_id(existing.id, changes)
        await self.uow.refresh(existing)
        return existing


class ProfileRepository(MySQLPersistenceRepository[ProfileModel]):
    table = ProfileTable

    async def existing_ids(
        self, configuration_id: int, limit: int
    ) -> list[int]:
        result = await self.uow.execute(
            select(col(ProfileTable.id))
            .where(col(ProfileTable.configuration_id) == configuration_id)
            .limit(limit)
            .with_for_update()
        )
        return list(result.scalars().all())

    async def selected(self, ids: list[int]) -> list[ProfileModel]:
        result = await self.uow.execute(
            select(ProfileTable)
            .where(col(ProfileTable.id).in_(ids))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def assigned_targets(
        self, subscription_id: int, configuration_ids: list[int]
    ) -> list[ProfileModel]:
        result = await self.uow.execute(
            select(ProfileTable)
            .where(
                col(ProfileTable.subscription_id) == subscription_id,
                col(ProfileTable.configuration_id).in_(configuration_ids),
            )
            .order_by(col(ProfileTable.id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def for_configurations(
        self, ids: list[int], limit: int
    ) -> list[ProfileModel]:
        result = await self.uow.execute(
            select(ProfileTable)
            .where(col(ProfileTable.configuration_id).in_(ids))
            .order_by(col(ProfileTable.id))
            .limit(limit)
            .with_for_update()
        )
        return list(result.scalars().all())

    async def for_subscription(
        self, subscription_id: int, limit: int
    ) -> list[ProfileModel]:
        result = await self.uow.execute(
            select(ProfileTable)
            .where(col(ProfileTable.subscription_id) == subscription_id)
            .order_by(col(ProfileTable.id))
            .limit(limit)
            .with_for_update()
        )
        return list(result.scalars().all())

    async def create_many(self, rows: list[ProfileModel]) -> None:
        columns = {
            name: ProfileTable.__table__.c[name]
            for name in (
                "configuration_id",
                "subscription_id",
                "client_address",
                "encrypted_credentials",
            )
        }
        await self.bulk_insert(rows, insert_columns=columns)

    async def mark_applied(
        self, id: int, generation: int | None, revision: int | None
    ) -> None:
        await self.uow.execute(
            update(ProfileTable)
            .where(col(ProfileTable.id) == id)
            .values(applied_generation=generation, applied_revision=revision)
        )

    async def mark_applied_many(
        self, updates: list[ProfileAppliedUpdate]
    ) -> None:
        if not updates:
            return
        rows = [
            ProfileModel.patch(
                id=item.profile_id,
                applied_generation=item.generation,
                applied_revision=item.revision,
            )
            for item in updates
        ]
        columns = {
            name: ProfileTable.__table__.c[name]
            for name in ("applied_generation", "applied_revision")
        }
        await self.bulk_update(rows, update_columns=columns)

    async def invalidate_many(self, ids: list[int]) -> None:
        await self.update_by_ids(
            ids, ProfileModel.patch(applied_revision=None).to_changes()
        )

    async def by_subscription(
        self, configuration_id: int, subscription_id: int
    ) -> ProfileModel | None:
        result = await self.uow.execute(
            select(ProfileTable).where(
                col(ProfileTable.configuration_id) == configuration_id,
                col(ProfileTable.subscription_id) == subscription_id,
            )
        )
        return result.scalar_one_or_none()

    async def page(
        self, configuration_id: int, offset: int, limit: int
    ) -> PagedType[ProfileModel]:
        query = (
            select(ProfileTable)
            .where(col(ProfileTable.configuration_id) == configuration_id)
            .order_by(col(ProfileTable.id).desc())
        )
        result = await fetch_page(self.uow, query, offset=offset, limit=limit)
        return result


class SubscriptionLinkRepository(
    MySQLPersistenceRepository[SubscriptionLinkModel]
):
    table = SubscriptionLinkTable

    async def by_subscription(
        self, subscription_id: int
    ) -> SubscriptionLinkModel | None:
        result = await self.uow.execute(
            select(SubscriptionLinkTable).where(
                col(SubscriptionLinkTable.subscription_id) == subscription_id
            )
        )
        return result.scalar_one_or_none()

    async def by_subscriptions_many(
        self, subscription_ids: list[int]
    ) -> list[SubscriptionLinkModel]:
        selected = sorted(set(subscription_ids))
        if not selected:
            return []
        result = await self.uow.execute(
            select(SubscriptionLinkTable)
            .where(col(SubscriptionLinkTable.subscription_id).in_(selected))
            .order_by(col(SubscriptionLinkTable.subscription_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def create_many(self, rows: list[SubscriptionLinkModel]) -> None:
        if not rows:
            return
        columns = {
            name: SubscriptionLinkTable.__table__.c[name]
            for name in ("subscription_id", "token_hash", "encrypted_token")
        }
        await self.bulk_insert(rows, insert_columns=columns)

    async def replace_many(self, rows: list[SubscriptionLinkModel]) -> None:
        if not rows:
            return
        columns = {
            name: SubscriptionLinkTable.__table__.c[name]
            for name in ("token_hash", "encrypted_token")
        }
        await self.bulk_update(rows, update_columns=columns)

    async def by_token(self, token_hash: str) -> SubscriptionLinkModel | None:
        result = await self.uow.execute(
            select(SubscriptionLinkTable).where(
                col(SubscriptionLinkTable.token_hash) == token_hash
            )
        )
        return result.scalar_one_or_none()

    async def replace(
        self, link: SubscriptionLinkModel, changes: SubscriptionLinkModel
    ) -> SubscriptionLinkModel:
        await self.update_row_by_id(link.id, changes)
        await self.uow.refresh(link)
        return link


class InboundPortRepository(MySQLPersistenceRepository[InboundPortModel]):
    table = InboundPortTable


class ConfigurationJsonRevisionRepository(
    MySQLPersistenceRepository[ConfigurationJsonRevisionModel]
):
    table = ConfigurationJsonRevisionTable

    async def page(
        self, configuration_id: int, offset: int, limit: int
    ) -> PagedType[ConfigurationJsonRevisionModel]:
        result = await fetch_page(
            self.uow,
            select(self.table)
            .where(col(self.table.configuration_id) == configuration_id)
            .order_by(col(self.table.revision).desc()),
            offset=offset,
            limit=limit,
        )
        return result
