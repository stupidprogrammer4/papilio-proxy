import asyncio
import getpass
import sys

from papilio.core.config import get_settings
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.uow import MySQLUnitOfWork

from src.config.settings import PapilioSettings
from src.modules.accounts.staff.app.passwords import Passwords
from src.modules.accounts.staff.app.services import StaffAuth
from src.modules.accounts.staff.infra.mysql import StaffRepository
from src.modules.accounts.staff.infra.readers import StaffSessionReader


async def create(username: str, password: str) -> None:
    settings = get_settings(PapilioSettings)
    if settings.db is None:
        raise RuntimeError("Configure db before creating an owner")
    connection = DBConnection(
        dsn=settings.db.dsn,
        pool_size=settings.db.pool_size,
        max_overflow=settings.db.max_overflow,
        pool_timeout=settings.db.pool_timeout,
        pool_recycle=settings.db.pool_recycle,
        uow_factory=MySQLUnitOfWork,
    )
    try:
        async with connection.uow() as unit:
            service = StaffAuth(
                StaffRepository(unit),
                Passwords(settings),
                settings,
                StaffSessionReader(unit),
            )
            await service.create_owner(username, password)
    finally:
        await connection.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/create_owner.py USERNAME")
    secret = getpass.getpass("Owner password: ")
    asyncio.run(create(sys.argv[1], secret))
