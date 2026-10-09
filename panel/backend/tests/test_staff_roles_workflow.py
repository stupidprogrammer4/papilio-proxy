import asyncio
import os
from contextvars import Context
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url

from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowTest,
)


class StaffRoleWorkflowTest(StaffAdministrationWorkflowTest):
    async def role(self, code, scopes, active=True):
        result = await self.post(
            "/v1/admin/roles",
            dict(
                code=code + self.suffix,
                title="نقش آزمایشی",
                scopes=scopes,
                is_active=active,
                reason="تعریف نقش",
            ),
        )
        return result

    async def assign(self, staff, roles, previous=None, mode="replace"):
        result = await self.client.put(
            f"/v1/admin/staff/{staff['id']}/roles",
            headers=self.headers,
            json=dict(
                mode=mode,
                role_ids=roles,
                expected_role_ids=previous or [],
                reason="تخصیص نقش",
            ),
        )
        return result

    async def test_role_permissions_live_modes_revisions_and_history(self):
        customer = await self.role("customers_", ["customers:read"])
        payment = await self.role("payments_", ["payments:read"])
        staff = await self.post(
            "/v1/admin/staff",
            dict(
                username="role_user_" + self.suffix,
                password="staff888",
                is_active=True,
                scopes=[],
            ),
        )
        client, _ = await self.login_staff(staff["username"], "staff888")
        try:
            self.assertEqual(
                (await client.get("/v1/admin/customers")).status_code, 403
            )
            assigned = await self.assign(staff, [customer["id"]])
            self.assertEqual(assigned.status_code, 200)
            self.assertEqual(assigned.json()["data"]["scopes"], [])
            self.assertEqual(
                assigned.json()["data"]["effective_scopes"], ["customers:read"]
            )
            self.assertEqual(
                (await client.get("/v1/admin/customers")).status_code, 200
            )
            added = await self.assign(
                staff, [payment["id"]], [customer["id"]], "add"
            )
            self.assertEqual(added.status_code, 200)
            self.assertEqual(
                (await client.get("/v1/admin/payments/topups")).status_code,
                200,
            )
            stale = await self.assign(staff, [], [customer["id"]])
            self.assertEqual(stale.status_code, 409)
            deactivated = dict(
                title="نقش متوقف",
                scopes=["customers:read"],
                is_active=False,
                expected_revision=1,
                reason="توقف نقش",
            )
            changed = await self.client.put(
                f"/v1/admin/roles/{customer['id']}",
                headers=self.headers,
                json=deactivated,
            )
            self.assertEqual(changed.status_code, 200)
            self.assertEqual(
                (await client.get("/v1/admin/customers")).status_code, 403
            )
            self.assertEqual(
                (await client.get("/v1/admin/payments/topups")).status_code,
                200,
            )
            self.assertEqual(
                (
                    await self.client.put(
                        f"/v1/admin/roles/{customer['id']}",
                        headers=self.headers,
                        json=deactivated,
                    )
                ).status_code,
                409,
            )
            deactivated.update(expected_revision=2, is_active=True)
            self.assertEqual(
                (
                    await self.client.put(
                        f"/v1/admin/roles/{customer['id']}",
                        headers=self.headers,
                        json=deactivated,
                    )
                ).status_code,
                200,
            )
            self.assertEqual(
                (await client.get("/v1/admin/customers")).status_code, 200
            )
            removed = await self.assign(
                staff,
                [payment["id"]],
                [customer["id"], payment["id"]],
                "remove",
            )
            self.assertEqual(removed.status_code, 200)
            self.assertEqual(
                (await client.get("/v1/admin/payments/topups")).status_code,
                403,
            )
            no_op = await self.assign(
                staff, [customer["id"]], [customer["id"]]
            )
            self.assertEqual(no_op.status_code, 200)
            missing = await self.assign(
                staff, [payment["id"] + customer["id"] + 1], [customer["id"]]
            )
            self.assertEqual(missing.status_code, 404)
            history = await self.get(
                f"/v1/admin/roles/{customer['id']}/history?per_page=1&page=2"
            )
            self.assertEqual(history["meta"]["pager"]["total_items"], 3)
            self.assertEqual(history["data"][0]["revision"], 2)
            assignments = await self.get(
                f"/v1/admin/staff/{staff['id']}/roles/history?per_page=1&page=2"
            )
            self.assertEqual(assignments["meta"]["pager"]["total_items"], 3)
            self.assertEqual(
                set(assignments["data"][0]["role_ids"]),
                {customer["id"], payment["id"]},
            )
            self.assertEqual(
                assignments["data"][0]["previous_role_ids"], [customer["id"]]
            )
            page = await self.get(
                "/v1/admin/roles?q=" + self.suffix + "&per_page=1"
            )
            self.assertEqual(len(page["data"]), 1)
            self.assertEqual(page["meta"]["pager"]["total_items"], 2)
            async with self.connection.uow() as unit:
                row = await unit.execute(
                    text(
                        "SELECT COUNT(*) FROM tbl_staff_role_memberships "
                        "WHERE staff_id=:id"
                    ),
                    {"id": staff["id"]},
                )
                self.assertEqual(row.scalar_one(), 1)
        finally:
            await client.aclose()

    async def test_role_authority_inactive_capacity_and_concurrent_edits(self):
        role = await self.role(
            "delegate_",
            ["staff:read", "staff:create", "staff:update", "customers:read"],
        )
        payment = await self.role("money_", ["payments:read"])
        inactive = await self.role("inactive_", ["customers:read"], False)
        staff = await self.post(
            "/v1/admin/staff",
            dict(
                username="delegate_role_" + self.suffix,
                password="staff888",
                is_active=True,
                scopes=[],
            ),
        )
        self.assertEqual(
            (await self.assign(staff, [role["id"]])).status_code, 200
        )
        client, headers = await self.login_staff(staff["username"], "staff888")
        try:
            child = await client.post(
                "/v1/admin/staff",
                headers=headers,
                json=dict(
                    username="role_child_" + self.suffix,
                    password="staff888",
                    is_active=True,
                    scopes=[],
                ),
            )
            self.assertEqual(child.status_code, 200)
            child = child.json()["data"]
            granted = await client.put(
                f"/v1/admin/staff/{child['id']}/roles",
                headers=headers,
                json=dict(
                    mode="add",
                    role_ids=[payment["id"]],
                    expected_role_ids=[],
                    reason="تخصیص بیش از اختیار",
                ),
            )
            self.assertEqual(granted.status_code, 403)
            denied = await client.post(
                "/v1/admin/roles",
                headers=headers,
                json=dict(
                    code="escape_" + self.suffix,
                    title="بیش از اختیار",
                    is_active=True,
                    scopes=["payments:read"],
                    reason="تعریف نقش",
                ),
            )
            self.assertEqual(denied.status_code, 403)
            global_role = await self.client.post(
                "/v1/admin/roles",
                headers=self.headers,
                json=dict(
                    code="global_" + self.suffix,
                    title="مالک",
                    is_active=True,
                    scopes=["*"],
                    reason="نقش مالک",
                ),
            )
            self.assertEqual(global_role.status_code, 422)
            self.assertEqual(
                (await self.assign(child, [inactive["id"]])).status_code, 409
            )
            with patch.object(
                self.settings.operations,
                "staff_inactive_role_assignment",
                True,
            ):
                self.assertEqual(
                    (await self.assign(child, [inactive["id"]])).status_code,
                    200,
                )
            with patch.object(self.settings.operations, "max_staff_roles", 1):
                self.assertEqual(
                    (
                        await self.assign(
                            child,
                            [role["id"], payment["id"]],
                            [inactive["id"]],
                        )
                    ).status_code,
                    409,
                )
            with patch.object(self.settings.operations, "max_staff_grants", 1):
                denied = await self.client.post(
                    "/v1/admin/roles",
                    headers=self.headers,
                    json=dict(
                        code="capacity_" + self.suffix,
                        title="ظرفیت",
                        is_active=True,
                        scopes=["customers:read", "payments:read"],
                        reason="تعریف نقش",
                    ),
                )
                self.assertEqual(denied.status_code, 409)
            members = await self.get(
                f"/v1/admin/roles/{role['id']}/members?per_page=1&q={staff['username']}"
            )
            self.assertEqual(members["meta"]["pager"]["total_items"], 1)
            self.assertEqual(members["data"][0]["id"], staff["id"])
            with patch.object(
                self.settings.operations, "max_staff_role_members", 1
            ):
                limited = await self.assign(
                    child, [role["id"]], [inactive["id"]]
                )
                self.assertEqual(limited.status_code, 409)
            # Scoped editors cannot alter a role assigned to a direct owner.
            owner_id = (await self.get("/v1/admin/staff?q=" + self.username))[
                "data"
            ][0]["id"]
            self.assertEqual(
                (
                    await self.assign({"id": owner_id}, [role["id"]])
                ).status_code,
                200,
            )
            denied = await client.put(
                f"/v1/admin/roles/{role['id']}",
                headers=headers,
                json=dict(
                    title="تغییر مالک",
                    scopes=role["scopes"],
                    is_active=False,
                    expected_revision=1,
                    reason="تغییر نقش",
                ),
            )
            self.assertEqual(denied.status_code, 403)
            # Independent request contexts verify serialized revision winners.
            body = dict(
                title="ویرایش همزمان",
                scopes=["payments:read"],
                is_active=True,
                expected_revision=1,
                reason="ویرایش همزمان",
            )
            first = asyncio.create_task(
                self.client.put(
                    f"/v1/admin/roles/{payment['id']}",
                    headers=self.headers,
                    json=body,
                ),
                context=Context(),
            )
            second = asyncio.create_task(
                self.client.put(
                    f"/v1/admin/roles/{payment['id']}",
                    headers=self.headers,
                    json=body,
                ),
                context=Context(),
            )
            results = await asyncio.gather(first, second)
            self.assertEqual(
                sorted(item.status_code for item in results), [200, 409]
            )
            self.assertEqual(
                (await self.get(f"/v1/admin/roles/{payment['id']}/history"))[
                    "meta"
                ]["pager"]["total_items"],
                2,
            )
        finally:
            await client.aclose()

    async def test_prior_staff_sessions_and_grants_survive_role_upgrade(self):
        assert self.settings.db is not None
        migration = Config("alembic.ini")
        migration.set_main_option(
            "sqlalchemy.url",
            make_url(str(self.settings.db.dsn)).render_as_string(
                hide_password=False
            ),
        )
        with patch.dict(os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(
                command.downgrade, migration, "0026_automation_policies"
            )
            async with self.connection.uow() as unit:
                before = await unit.execute(
                    text("SELECT COUNT(*) FROM tbl_staff_sessions")
                )
                count = before.scalar_one()
                self.assertGreater(count, 0)
            await asyncio.to_thread(command.upgrade, migration, "head")
        self.assertEqual(
            (await self.client.get("/v1/admin/auth/me")).status_code, 200
        )
        self.assertEqual((await self.get("/v1/admin/roles"))["data"], [])
        async with self.connection.uow() as unit:
            result = await unit.execute(
                text("SELECT COUNT(*) FROM tbl_staff_sessions")
            )
            self.assertEqual(result.scalar_one(), count)
            result = await unit.execute(
                text("SELECT scope FROM tbl_staff_grants")
            )
            self.assertIn("*", result.scalars().all())
