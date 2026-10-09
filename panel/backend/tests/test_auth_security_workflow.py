import asyncio
import hashlib
import hmac
import os
import time
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
from papilio.infra.db.transaction import transaction
from papilio.infra.db.uow import MySQLUnitOfWork
from starlette.middleware import Middleware

from src.config.middleware import (
    RequestBodyLimitMiddleware,
    SecurityHeadersMiddleware,
)
from src.config.providers import infrastructure_providers
from src.config.settings import PapilioSettings
from src.modules.accounts.staff.app.passwords import Passwords
from src.modules.accounts.staff.app.services import StaffAuth
from src.modules.accounts.staff.domain.models import StaffModel
from src.modules.accounts.staff.infra.mysql import StaffRepository
from src.modules.accounts.staff.infra.readers import StaffSessionReader

TEST_URL = os.getenv("PAPILIO_TEST_DATABASE_URL")
REDIS_URL = os.getenv("PAPILIO_TEST_REDIS_URL")


@skipUnless(TEST_URL and REDIS_URL, "Requires isolated MySQL and Redis")
class AuthSecurityWorkflowTest(IsolatedAsyncioTestCase):
    async def test_native_login_rate_limit_body_limit_and_sms_validation(
        self,
    ) -> None:
        migration = Config("alembic.ini")
        migration.set_main_option("sqlalchemy.url", str(TEST_URL))
        with patch.dict(os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(command.upgrade, migration, "head")
        raw = yaml.safe_load(Path("config.yml.sample").read_text())
        raw["db"]["dsn"] = TEST_URL
        raw["redis"]["url"] = REDIS_URL
        raw["rate_limit"]["rules"]["papilio_admin_login"]["limit"] = 2
        settings = PapilioSettings.model_validate(raw)
        app = create_app(
            settings,
            providers=infrastructure_providers(settings),
            middleware=[
                Middleware(SecurityHeadersMiddleware),
                Middleware(
                    RequestBodyLimitMiddleware,
                    max_bytes=settings.operations.max_request_body_bytes,
                ),
            ],
            docs_url=None,
        )
        suffix = uuid4().hex
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, client=(suffix, 1234)),
                base_url="https://admin.example.com",
            ) as client:
                payload = {
                    "username": "missing_" + suffix[:12],
                    "password": "eight888",
                }
                headers = {"Origin": settings.public.admin_origin}
                first = await client.post(
                    "/v1/admin/auth/login", headers=headers, json=payload
                )
                second = await client.post(
                    "/v1/admin/auth/login", headers=headers, json=payload
                )
                self.assertEqual(first.status_code, 401)
                self.assertEqual(second.status_code, 401)
                rejected = await client.post(
                    "/v1/admin/auth/login",
                    headers={**headers, "X-Forwarded-For": "198.51.100.1"},
                    json={**payload, "username": "other_" + suffix[:12]},
                )
                self.assertEqual(rejected.status_code, 429)
                oversized = await client.post(
                    "/v1/admin/auth/login",
                    headers=headers,
                    content=b"x"
                    * (settings.operations.max_request_body_bytes + 1),
                )
                self.assertEqual(oversized.status_code, 413)

                async def chunks():
                    yield b"x" * settings.operations.max_request_body_bytes
                    yield b"x"

                streamed = await client.post(
                    "/v1/admin/auth/login", headers=headers, content=chunks()
                )
                self.assertEqual(streamed.status_code, 413)
                timestamp = str(int(time.time()))
                body = b'{"message":"invalid"}'
                signature = hmac.new(
                    settings.security.sms_webhook_key.encode(),
                    timestamp.encode() + b"." + body,
                    hashlib.sha256,
                ).hexdigest()
                invalid_sms = await client.post(
                    "/v1/webhooks/sms",
                    headers={
                        "X-Papilio-Timestamp": timestamp,
                        "X-Papilio-Signature": signature,
                        "Content-Type": "application/json",
                    },
                    content=body,
                )
                self.assertEqual(invalid_sms.status_code, 422)
                self.assertNotIn('"input"', invalid_sms.text)
                self.assertEqual(
                    invalid_sms.headers["cache-control"], "no-store"
                )
                huge_timestamp = await client.post(
                    "/v1/webhooks/sms",
                    headers={"X-Papilio-Timestamp": "9" * 5000},
                    content=b"{}",
                )
                self.assertEqual(huge_timestamp.status_code, 401)
        finally:
            await app.state.dishka_container.close()

    async def test_legacy_password_upgrades_after_authenticated_login(self):
        migration = Config("alembic.ini")
        migration.set_main_option("sqlalchemy.url", str(TEST_URL))
        with patch.dict(os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(command.upgrade, migration, "head")
        raw = yaml.safe_load(Path("config.yml.sample").read_text())
        raw["db"]["dsn"] = TEST_URL
        settings = PapilioSettings.model_validate(raw)
        assert settings.db is not None
        db = settings.db
        connection = DBConnection(
            dsn=db.dsn,
            pool_size=db.pool_size,
            max_overflow=db.max_overflow,
            pool_timeout=db.pool_timeout,
            pool_recycle=db.pool_recycle,
            uow_factory=MySQLUnitOfWork,
        )
        username = "legacy_" + uuid4().hex[:12]
        password = "legacy-test-password"
        salt = os.urandom(16)
        digest = await asyncio.to_thread(
            hashlib.scrypt, password.encode(), salt=salt, n=2**14, r=8, p=1
        )
        legacy_hash = f"scrypt${salt.hex()}${digest.hex()}"
        try:
            async with connection.uow() as unit:
                async with transaction():
                    await StaffRepository(unit).create(
                        StaffModel(
                            username=username,
                            password_hash=legacy_hash,
                            is_active=True,
                        )
                    )
            async with connection.uow() as unit:
                auth = StaffAuth(
                    StaffRepository(unit),
                    Passwords(settings),
                    settings,
                    StaffSessionReader(unit),
                )
                issued = await auth.login(username, password)
                self.assertEqual(issued.principal.username, username)
            async with connection.uow() as independent:
                stored = await StaffRepository(independent).by_username(
                    username
                )
                assert stored is not None
                self.assertFalse(stored.password_hash.startswith("scrypt$"))
                verified = await Passwords(settings).verify(
                    password, stored.password_hash
                )
                self.assertTrue(verified)
                rejected = await Passwords(settings).verify(
                    "wrong-password", stored.password_hash
                )
                self.assertFalse(rejected)
            async with connection.uow() as unit:
                auth = StaffAuth(
                    StaffRepository(unit),
                    Passwords(settings),
                    settings,
                    StaffSessionReader(unit),
                )
                issued = await auth.login(username, password)
                self.assertEqual(issued.principal.username, username)
        finally:
            await connection.dispose()
