from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from papilio_proxy.config.database import DatabaseConnection
from papilio_proxy.modules.brand.profile.domain.entities import BotBranding
from papilio_proxy.modules.brand.profile.infra.tables import BotBrandingModel


class MysqlBrandingRepository:
    def __init__(self, database: DatabaseConnection) -> None:
        self._sessions = async_sessionmaker(database.engine, expire_on_commit=False)

    async def get_branding(self) -> BotBranding:
        statement = select(BotBrandingModel).where(BotBrandingModel.id == 1)
        async with self._sessions() as session:
            record = await session.scalar(statement)
        if record is None:
            return BotBranding("", "", "")
        return BotBranding(
            name=record.name,
            short_description=record.short_description,
            description=record.description,
        )

    async def save_branding(self, branding: BotBranding) -> None:
        statement = insert(BotBrandingModel).values(
            id=1,
            name=branding.name,
            short_description=branding.short_description,
            description=branding.description,
        )
        statement = statement.on_duplicate_key_update(
            name=statement.inserted.name,
            short_description=statement.inserted.short_description,
            description=statement.inserted.description,
        )
        async with self._sessions() as session, session.begin():
            await session.execute(statement)
