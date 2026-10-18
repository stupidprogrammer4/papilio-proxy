import asyncio
import os
from unittest import IsolatedAsyncioTestCase, skipUnless
from unittest.mock import patch
from uuid import uuid4

from alembic import command
from alembic.config import Config
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import text
from sqlalchemy.engine import make_url

TEST_URL = os.getenv("PAPILIO_TEST_DATABASE_URL")
PRIOR = "0066_topup_revisions"
CURRENT = "0067_pref_catalog_capacity"


@skipUnless(TEST_URL, "Requires isolated MySQL")
class PreferencesCatalogCapacityMigrationTest(IsolatedAsyncioTestCase):
    async def test_expands_existing_rows_and_guards_lossy_downgrade(
        self,
    ) -> None:
        schema = "papilio_preferences_capacity_test_" + uuid4().hex[:12]
        base_url = make_url(str(TEST_URL))
        assert base_url.host == "127.0.0.1" and "test" in schema
        target_dsn = base_url.set(database=schema).render_as_string(
            hide_password=False
        )
        maintenance = DBConnection(
            dsn=str(TEST_URL),
            pool_size=2,
            max_overflow=0,
            pool_timeout=30,
            pool_recycle=1800,
            uow_factory=MySQLUnitOfWork,
        )
        target = DBConnection(
            dsn=target_dsn,
            pool_size=2,
            max_overflow=0,
            pool_timeout=30,
            pool_recycle=1800,
            uow_factory=MySQLUnitOfWork,
        )
        migration = Config("alembic.ini")
        migration.set_main_option("sqlalchemy.url", target_dsn)
        async with maintenance.uow() as unit:
            await unit.execute(text(f"CREATE DATABASE `{schema}`"))
        try:
            with patch.dict(
                os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}
            ):
                await asyncio.to_thread(command.upgrade, migration, PRIOR)
            prior_value = "prior-data-" + ("x" * 49_990)
            async with target.uow() as unit:
                await unit.execute(
                    text(
                        "INSERT INTO tbl_staff "
                        "(id,username,password_hash,is_active) "
                        "VALUES (991,:username,'test-hash',1)"
                    ),
                    {"username": "catalog_capacity_" + uuid4().hex[:12]},
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_preferences_revisions "
                        "(revision,values_json,changed_by_staff_id) "
                        "VALUES (991,:values_json,991)"
                    ),
                    {"values_json": prior_value},
                )
                await unit.commit()
            with patch.dict(
                os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}
            ):
                await asyncio.to_thread(command.upgrade, migration, CURRENT)
            oversized_value = "new-catalog-" + ("y" * 100_000)
            async with target.uow() as unit:
                await unit.execute(
                    text(
                        "INSERT INTO tbl_preferences_revisions "
                        "(revision,values_json,changed_by_staff_id) "
                        "VALUES (992,:values_json,991)"
                    ),
                    {"values_json": oversized_value},
                )
                await unit.commit()
            async with target.uow() as unit:
                stored = await unit.execute(
                    text(
                        "SELECT revision,values_json "
                        "FROM tbl_preferences_revisions "
                        "WHERE revision IN (991,992) ORDER BY revision"
                    )
                )
                self.assertEqual(
                    list(stored),
                    [(991, prior_value), (992, oversized_value)],
                )
            with patch.dict(
                os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "Preference data exceeds TEXT capacity"
                ):
                    await asyncio.to_thread(
                        command.downgrade, migration, PRIOR
                    )
        finally:
            await target.dispose()
            async with maintenance.uow() as unit:
                await unit.execute(text(f"DROP DATABASE `{schema}`"))
            await maintenance.dispose()
