import asyncio

from alembic import context
from papilio.core.bootstrap import Bootstrapper
from papilio.core.config import get_settings
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from src.config.settings import PapilioSettings

config = context.config
settings = get_settings(PapilioSettings)
Bootstrapper(settings.app.modules).boot_sqlmodels()
target_metadata = SQLModel.metadata
database = settings.db
if database is None:
    raise RuntimeError("Configure db in config.yml")
url = config.get_main_option("sqlalchemy.url") or database.dsn


def migrate(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def online() -> None:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(migrate)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(online())
