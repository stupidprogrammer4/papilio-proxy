"""Migrate the configured database and preserve/create its native owner."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[1] / "panel" / "backend"
if not (ROOT / "alembic.ini").is_file():
    ROOT = Path("/app")
sys.path.insert(0, str(ROOT))


async def ensure_owner(username: str, password: str) -> bool:
    from papilio.core.config import get_settings
    from papilio.infra.db.connection import DBConnection
    from papilio.infra.db.uow import MySQLUnitOfWork
    from scripts.create_owner import create
    from src.config.settings import PapilioSettings
    from src.modules.accounts.staff.infra.mysql import StaffRepository

    settings = get_settings(PapilioSettings)
    database = settings.db
    if database is None:
        raise RuntimeError("Configure native database settings")
    connection = DBConnection(
        dsn=database.dsn,
        pool_size=database.pool_size,
        max_overflow=database.max_overflow,
        pool_timeout=database.pool_timeout,
        pool_recycle=database.pool_recycle,
        uow_factory=MySQLUnitOfWork,
    )
    try:
        async with connection.uow() as unit:
            repository = StaffRepository(unit)
            existing = await repository.by_username(username)
            if existing is not None:
                grants = await repository.grants(existing.id)
                if "*" not in grants or not existing.is_active:
                    raise RuntimeError(
                        "Existing username is not an active owner"
                    )
                return False
    finally:
        await connection.dispose()
    await create(username, password)
    return True


async def require_fresh_or_current(head: str) -> None:
    from papilio.core.config import get_settings
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from src.config.settings import PapilioSettings

    database = get_settings(PapilioSettings).db
    if database is None:
        raise RuntimeError("Configure native database settings")
    engine = create_async_engine(database.dsn, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as connection:
            tables = await connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema=DATABASE()"
                )
            )
            names = set(tables.scalars().all())
            if not names:
                return
            if "alembic_version" not in names:
                raise RuntimeError(
                    "Existing unversioned database requires review"
                )
            versions = await connection.execute(
                text("SELECT version_num FROM alembic_version")
            )
            if set(versions.scalars().all()) != {head}:
                raise RuntimeError(
                    "Schema upgrade requires verified encrypted backup; "
                    "use the documented native migration workflow"
                )
    finally:
        await engine.dispose()


def main() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    username = os.environ.get("OWNER_USERNAME")
    path = Path(
        os.environ.get("OWNER_PASSWORD_FILE", "/run/secrets/owner-password")
    )
    if not username or path.is_symlink() or not path.is_file():
        raise RuntimeError(
            "Configure owner username and private password file"
        )
    password = path.read_text(encoding="utf-8")
    os.environ.setdefault("PAPILIO_CONFIG", "/app/config.yml")
    configuration = Config(str(ROOT / "alembic.ini"))
    configuration.set_main_option("script_location", str(ROOT / "migrations"))
    head = ScriptDirectory.from_config(configuration).get_current_head()
    if head is None:
        raise RuntimeError("Native migration head unavailable")
    asyncio.run(require_fresh_or_current(head))
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    created = asyncio.run(ensure_owner(username, password))
    print(
        "Native schema ready; owner created."
        if created
        else "Native schema ready; existing owner/password preserved."
    )


if __name__ == "__main__":
    try:
        main()
    except (
        RuntimeError,
        ValueError,
        OSError,
        SQLAlchemyError,
        subprocess.CalledProcessError,
    ):
        raise SystemExit(
            "Bootstrap rejected. Check private settings, database readiness, "
            "owner identity and backup/migration requirements."
        ) from None
