import asyncio
from contextvars import Context
from unittest.mock import patch

import httpx
from sqlalchemy import text
from sqlalchemy.engine import make_url

from tests.lock_observation import MySQLLockObservation
from tests.test_automation_workflow import TEST_URL, AutomationWorkflowFixture


class StaffAdministrationWorkflowFixture(AutomationWorkflowFixture):
    async def asyncSetUp(self):
        from uuid import uuid4

        from papilio.infra.db.connection import DBConnection
        from papilio.infra.db.uow import MySQLUnitOfWork

        self.schema = "papilio_upgrade_test_staff_" + uuid4().hex[:12]
        self.maintenance = DBConnection(
            dsn=str(TEST_URL),
            pool_size=2,
            max_overflow=0,
            pool_timeout=30,
            pool_recycle=1800,
            uow_factory=MySQLUnitOfWork,
        )
        async with self.maintenance.uow() as unit:
            await unit.execute(text(f"CREATE DATABASE `{self.schema}`"))
        url = make_url(str(TEST_URL)).set(database=self.schema)
        with patch(
            "tests.test_automation_workflow.TEST_URL",
            url.render_as_string(hide_password=False),
        ):
            await super().asyncSetUp()

    async def asyncTearDown(self):
        await super().asyncTearDown()
        async with self.maintenance.uow() as unit:
            await unit.execute(text(f"DROP DATABASE `{self.schema}`"))
        await self.maintenance.dispose()

    async def login_staff(self, username, password):
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="https://admin.example.com",
        )
        login = await client.post(
            "/v1/admin/auth/login",
            headers={"Origin": self.settings.public.admin_origin},
            json={"username": username, "password": password},
        )
        self.assertEqual(login.status_code, 200)
        return client, {
            "Origin": self.settings.public.admin_origin,
            "X-CSRF-Token": login.json()["csrf_token"],
        }


class StaffAdministrationWorkflowTest(StaffAdministrationWorkflowFixture):
    async def test_scoped_delegation_stale_edits_password_and_customer_context(
        self,
    ):
        staff = await self.post(
            "/v1/admin/staff",
            {
                "username": "delegate_" + self.suffix,
                "password": "staff888",
                "is_active": True,
                "scopes": [
                    "staff:read",
                    "staff:create",
                    "staff:update",
                    "customers:read",
                ],
            },
        )
        self.assertNotIn("password_hash", staff)
        self.assertEqual(staff["scopes"], sorted(staff["scopes"]))
        delegate, headers = await self.login_staff(
            staff["username"], "staff888"
        )
        try:
            forbidden = await delegate.get("/v1/admin/payments/topups")
            self.assertEqual(forbidden.status_code, 403)
            page = await delegate.get(
                "/v1/admin/staff", params={"q": self.suffix, "per_page": 1}
            )
            self.assertEqual(page.status_code, 200)
            self.assertEqual(page.json()["meta"]["pager"]["total_items"], 2)
            self.assertEqual(len(page.json()["data"]), 1)
            escaped = await delegate.post(
                "/v1/admin/staff",
                headers=headers,
                json={
                    "username": "escape_" + self.suffix,
                    "password": "staff888",
                    "is_active": True,
                    "scopes": ["*"],
                },
            )
            self.assertEqual(escaped.status_code, 403)
            child = await delegate.post(
                "/v1/admin/staff",
                headers=headers,
                json={
                    "username": "child_" + self.suffix,
                    "password": "staff888",
                    "is_active": True,
                    "scopes": ["customers:read"],
                },
            )
            self.assertEqual(child.status_code, 200)
            owner_page = (
                await self.get("/v1/admin/staff?q=" + self.username)
            )["data"]
            owner = (await self.get(f"/v1/admin/staff/{owner_page[0]['id']}"))[
                "data"
            ]
            denied = await delegate.put(
                f"/v1/admin/staff/{owner['id']}/password",
                headers=headers,
                json={"password": "changed888"},
            )
            self.assertEqual(denied.status_code, 403)
            payload = {
                "is_active": True,
                "scopes": ["staff:read", "customers:read"],
                "expected_is_active": True,
                "expected_scopes": staff["scopes"],
            }
            updated = await self.client.put(
                f"/v1/admin/staff/{staff['id']}/access",
                headers=self.headers,
                json=payload,
            )
            self.assertEqual(updated.status_code, 200)
            write_denied = await delegate.post(
                "/v1/admin/staff",
                headers=headers,
                json={
                    "username": "later_" + self.suffix,
                    "password": "staff888",
                    "is_active": True,
                    "scopes": [],
                },
            )
            self.assertEqual(write_denied.status_code, 403)
            stale = await self.client.put(
                f"/v1/admin/staff/{staff['id']}/access",
                headers=self.headers,
                json=payload,
            )
            self.assertEqual(stale.status_code, 409)
            short = await self.client.put(
                f"/v1/admin/staff/{staff['id']}/password",
                headers=self.headers,
                json={"password": "seven77"},
            )
            self.assertEqual(short.status_code, 422)
            changed = await self.client.put(
                f"/v1/admin/staff/{staff['id']}/password",
                headers=self.headers,
                json={"password": "changed888"},
            )
            self.assertEqual(changed.status_code, 204)
            self.assertEqual(
                (await delegate.get("/v1/admin/auth/me")).status_code, 401
            )
            old = await delegate.post(
                "/v1/admin/auth/login",
                headers={"Origin": self.settings.public.admin_origin},
                json={"username": staff["username"], "password": "staff888"},
            )
            self.assertEqual(old.status_code, 401)
            renewed, _ = await self.login_staff(
                staff["username"], "changed888"
            )
            try:
                self.assertEqual(
                    (await renewed.get("/v1/admin/customers")).status_code, 200
                )
            finally:
                await renewed.aclose()
            customer = await self.post(
                "/v1/admin/customers",
                {"display_name": "نام نخست", "telegram_id": 9876543210},
            )
            renamed = await self.client.put(
                f"/v1/admin/customers/{customer['id']}/profile",
                headers=self.headers,
                json={"display_name": "نام تازه", "telegram_id": 123},
            )
            self.assertEqual(renamed.status_code, 200)
            self.assertEqual(renamed.json()["data"]["telegram_id"], 9876543210)
            self.assertEqual(
                renamed.json()["data"]["display_name"], "نام تازه"
            )
            async with self.connection.uow() as independent:
                stored = (
                    await independent.execute(
                        text(
                            "SELECT display_name, telegram_id "
                            "FROM tbl_customers WHERE id=:id"
                        ),
                        {"id": customer["id"]},
                    )
                ).one()
                self.assertEqual(stored.display_name, "نام تازه")
                self.assertEqual(stored.telegram_id, 9876543210)
        finally:
            await delegate.aclose()

    async def test_concurrent_owner_deactivation_preserves_one_active_owner(
        self,
    ):
        page = (await self.get("/v1/admin/staff?q=" + self.username))["data"]
        owner = (await self.get(f"/v1/admin/staff/{page[0]['id']}"))["data"]
        second = await self.post(
            "/v1/admin/staff",
            {
                "username": "owner2_" + self.suffix,
                "password": "staff888",
                "is_active": True,
                "scopes": ["*"],
            },
        )
        other, headers = await self.login_staff(second["username"], "staff888")
        body = {
            "is_active": False,
            "scopes": ["*"],
            "expected_is_active": True,
            "expected_scopes": ["*"],
        }
        try:
            replies = await asyncio.gather(
                self.client.put(
                    f"/v1/admin/staff/{owner['id']}/access",
                    headers=self.headers,
                    json=body,
                ),
                other.put(
                    f"/v1/admin/staff/{second['id']}/access",
                    headers=headers,
                    json=body,
                ),
            )
            self.assertEqual(
                sorted(response.status_code for response in replies),
                [200, 409],
            )
            async with self.connection.uow() as independent:
                active = (
                    await independent.execute(
                        text(
                            "SELECT count(*) FROM tbl_staff s "
                            "JOIN tbl_staff_grants g ON g.staff_id=s.id "
                            "WHERE s.is_active=1 AND g.scope='*'"
                        )
                    )
                ).scalar_one()
                self.assertEqual(active, 1)
        finally:
            await other.aclose()

    async def test_password_reset_fences_an_old_password_login_before_commit(
        self,
    ):
        from papilio.infra.db.transaction import transaction
        from pydantic import SecretStr

        from src.modules.accounts.staff.app.administration import (
            StaffAdministration,
        )
        from src.modules.accounts.staff.app.passwords import Passwords
        from src.modules.accounts.staff.domain.dtos import StaffPasswordWrite
        from src.modules.accounts.staff.infra.mysql import StaffRepository
        from src.modules.accounts.staff.infra.readers import (
            StaffAuthorityReader,
        )

        staff = await self.post(
            "/v1/admin/staff",
            {
                "username": "racing_" + self.suffix,
                "password": "staff888",
                "is_active": True,
                "scopes": ["customers:read"],
            },
        )
        owner = (await self.get("/v1/admin/staff?q=" + self.username))["data"][
            0
        ]
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="https://admin.example.com",
        )
        login = None
        try:
            async with self.connection.uow() as unit:
                async with transaction(unit):
                    command = StaffAdministration(
                        StaffRepository(unit),
                        StaffAuthorityReader(unit),
                        Passwords(self.settings),
                        self.settings,
                    )
                    await command.reset_password(
                        staff["id"],
                        StaffPasswordWrite(password=SecretStr("newstaff888")),
                        owner["id"],
                    )
                    login = asyncio.create_task(
                        client.post(
                            "/v1/admin/auth/login",
                            headers={
                                "Origin": self.settings.public.admin_origin
                            },
                            json={
                                "username": staff["username"],
                                "password": "staff888",
                            },
                        ),
                        context=Context(),
                    )
                    assert self.settings.db is not None
                    blocked = await asyncio.to_thread(
                        MySQLLockObservation().wait_for_queries,
                        self.settings.db.dsn,
                        "tbl_staff",
                        ("SELECT", "INSERT"),
                        1,
                        5,
                        0.02,
                        False,
                    )
                    self.assertTrue(
                        blocked,
                        "The login must reach a DB lock before reset commits",
                    )
                    self.assertFalse(login.done())
            reply = await asyncio.wait_for(login, timeout=5)
            self.assertEqual(reply.status_code, 401)
            fresh, _ = await self.login_staff(staff["username"], "newstaff888")
            await fresh.aclose()
        finally:
            if login is not None and not login.done():
                login.cancel()
                await asyncio.gather(login, return_exceptions=True)
            await client.aclose()
