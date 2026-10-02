from __future__ import annotations

from papilio.infra.db.connection import DBConnection
from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared schema registry; each Papilio module owns its own tables."""


type DatabaseConnection = DBConnection[MySQLUnitOfWork]


def create_mysql_engine(database_url: str | DatabaseConnection) -> AsyncEngine:
    """Runtime repositories share Papilio's pool; standalone tools own theirs."""
    if isinstance(database_url, DBConnection):
        return database_url.engine
    database = DBConnection(
        dsn=database_url,
        pool_size=5,
        max_overflow=5,
        pool_timeout=30,
        pool_recycle=1800,
        uow_factory=MySQLUnitOfWork,
    )
    database.engine.sync_engine.hide_parameters = True
    return database.engine
