import asyncio
import os
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, skipUnless
from unittest.mock import patch
from uuid import uuid4

import httpx
import yaml
from alembic import command
from alembic.config import Config
from papilio.api.application import create_app
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.uow import MySQLUnitOfWork

from src.config.providers import infrastructure_providers
from src.config.settings import PapilioSettings
from src.modules.network.routing.app.services import HostGroupService
from src.modules.network.routing.infra.mysql import HostGroupRepository
from src.modules.operations.preferences.app.services import PreferencesService
from src.modules.operations.preferences.infra.mysql import (
    PreferencesRepository,
)
from src.modules.sales.catalog.app.services import PlanService
from src.modules.sales.catalog.domain.dtos import PlanCreate, PlanSetActive
from src.modules.sales.catalog.infra.mysql import PlanRepository

TEST_URL = os.getenv("PAPILIO_TEST_DATABASE_URL")


def configured_settings() -> PapilioSettings:
    raw = yaml.safe_load(Path("config.yml.sample").read_text())
    raw["rate_limit"]["enabled"] = False
    raw["db"]["dsn"] = TEST_URL
    raw["db"]["test_dsn"] = TEST_URL
    return PapilioSettings.model_validate(raw)


@skipUnless(TEST_URL, "Requires an isolated PAPILIO_TEST_DATABASE_URL")
class PlanWorkflowTest(IsolatedAsyncioTestCase):
    async def test_migration_create_activate_and_public_page(self) -> None:
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", str(TEST_URL))
        with patch.dict(os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(command.upgrade, config, "head")

        settings = configured_settings()
        assert settings.db is not None
        connection = DBConnection(
            dsn=settings.db.dsn,
            pool_size=2,
            max_overflow=0,
            pool_timeout=30,
            pool_recycle=1800,
            uow_factory=MySQLUnitOfWork,
        )
        code = "integration_" + uuid4().hex[:16]
        try:
            async with connection.uow() as unit:
                service = PlanService(
                    PlanRepository(unit),
                    settings,
                    HostGroupService(HostGroupRepository(unit), settings),
                    PreferencesService(PreferencesRepository(unit), settings),
                )
                created = await service.create(
                    PlanCreate(
                        code=code,
                        title="آزمایش",
                        quota_bytes=2_147_483_648,
                        duration_days=30,
                        price_rial=990_000,
                    )
                )
            async with connection.uow() as independent:
                service = PlanService(
                    PlanRepository(independent),
                    settings,
                    HostGroupService(
                        HostGroupRepository(independent), settings
                    ),
                    PreferencesService(
                        PreferencesRepository(independent), settings
                    ),
                )
                found = await service.get(created.id)
                self.assertFalse(found.is_active)
            app = create_app(
                settings,
                providers=infrastructure_providers(settings),
                middleware=(),
                docs_url=None,
            )
            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://testserver",
                ) as client:
                    response = await client.get("/v1/plans")
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(
                    code, {row["code"] for row in response.json()["data"]}
                )
                async with connection.uow() as independent:
                    service = PlanService(
                        PlanRepository(independent),
                        settings,
                        HostGroupService(
                            HostGroupRepository(independent), settings
                        ),
                        PreferencesService(
                            PreferencesRepository(independent), settings
                        ),
                    )
                    activated = await service.set_active(
                        created.id, PlanSetActive(is_active=True)
                    )
                    self.assertTrue(activated.is_active)
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://testserver",
                ) as client:
                    response = await client.get("/v1/plans")
                self.assertEqual(response.status_code, 200)
                self.assertIn(
                    code, {row["code"] for row in response.json()["data"]}
                )
            finally:
                await app.state.dishka_container.close()
        finally:
            await connection.dispose()
