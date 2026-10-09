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
from src.modules.accounts.staff.app.passwords import Passwords
from src.modules.accounts.staff.app.services import StaffAuth
from src.modules.accounts.staff.infra.mysql import StaffRepository
from src.modules.accounts.staff.infra.readers import StaffSessionReader
from src.modules.network.routing.app.services import HostGroupService
from src.modules.network.routing.infra.mysql import HostGroupRepository
from src.modules.operations.preferences.app.services import PreferencesService
from src.modules.operations.preferences.infra.mysql import (
    PreferencesRepository,
)
from src.modules.sales.catalog.app.services import PlanService
from src.modules.sales.catalog.domain.dtos import PlanSearch
from src.modules.sales.catalog.infra.mysql import PlanRepository

TEST_URL = os.getenv("PAPILIO_TEST_DATABASE_URL")


@skipUnless(TEST_URL, "Requires an isolated PAPILIO_TEST_DATABASE_URL")
class AdminPlanWorkflowTest(IsolatedAsyncioTestCase):
    async def test_staff_login_and_scoped_plan_write(self) -> None:
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", str(TEST_URL))
        with patch.dict(os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(command.upgrade, config, "head")
        raw = yaml.safe_load(Path("config.yml.sample").read_text())
        raw["rate_limit"]["enabled"] = False
        raw["db"]["dsn"] = TEST_URL
        raw["db"]["test_dsn"] = TEST_URL
        settings = PapilioSettings.model_validate(raw)
        assert settings.db is not None
        connection = DBConnection(
            dsn=settings.db.dsn,
            pool_size=2,
            max_overflow=0,
            pool_timeout=30,
            pool_recycle=1800,
            uow_factory=MySQLUnitOfWork,
        )
        username = "owner_" + uuid4().hex[:12]
        password = "local-only-password-123"
        code = "api_" + uuid4().hex[:12]
        try:
            async with connection.uow() as unit:
                auth = StaffAuth(
                    StaffRepository(unit),
                    Passwords(settings),
                    settings,
                    StaffSessionReader(unit),
                )
                await auth.create_owner(username, password)

            app = create_app(
                settings,
                providers=infrastructure_providers(settings),
                middleware=(),
                docs_url=None,
            )
            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="https://admin.example.com",
                ) as client:
                    denied = await client.get("/v1/admin/plans")
                    self.assertEqual(denied.status_code, 401)
                    login = await client.post(
                        "/v1/admin/auth/login",
                        headers={"Origin": settings.public.admin_origin},
                        json={"username": username, "password": password},
                    )
                    self.assertEqual(login.status_code, 200)
                    csrf = login.json()["csrf_token"]
                    payload = {
                        "code": code,
                        "title": "پلن آزمایشی",
                        "quota_bytes": 1_073_741_824,
                        "duration_days": 30,
                        "price_rial": 590_000,
                    }
                    rejected = await client.post(
                        "/v1/admin/plans", json=payload
                    )
                    self.assertEqual(rejected.status_code, 403)
                    created = await client.post(
                        "/v1/admin/plans",
                        json=payload,
                        headers={
                            "Origin": settings.public.admin_origin,
                            "X-CSRF-Token": csrf,
                        },
                    )
                    self.assertEqual(created.status_code, 200)
                    self.assertEqual(created.json()["data"]["code"], code)
                    self.assertFalse(created.json()["data"]["is_active"])

                async with connection.uow() as independent:
                    plan = PlanService(
                        PlanRepository(independent),
                        settings,
                        HostGroupService(
                            HostGroupRepository(independent), settings
                        ),
                        PreferencesService(
                            PreferencesRepository(independent), settings
                        ),
                    )
                    found = await plan.search(PlanSearch(q="پلن آزمایشی"))
                    self.assertIn(code, {row.code for row in found.items})
            finally:
                await app.state.dishka_container.close()
        finally:
            await connection.dispose()
