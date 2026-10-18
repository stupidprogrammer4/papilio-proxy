import asyncio
from contextvars import Context
from uuid import uuid4

import httpx
from sqlalchemy import text

from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowTest,
)


class ResellerAccountsWorkflowTest(StaffAdministrationWorkflowTest):
    async def organization(self, **changes):
        suffix = uuid4().hex[:12]
        body = {
            "code": "dealer_" + suffix,
            "title": "نمایندگی " + suffix,
            "owner": {"username": "dealer_" + suffix, "password": "dealer888"},
            "access": {
                "login_enabled": True,
                "sales_enabled": True,
                "renewals_enabled": True,
            },
            **changes,
        }
        result = await self.post("/v1/admin/resellers", body)
        self.assertNotIn("password", str(result))
        self.assertNotIn("scopes_json", str(result))
        return result

    async def login_reseller(self, username, password="dealer888"):
        capacity = self.settings.resellers
        assert capacity is not None
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url=capacity.portal_origin,
        )
        result = await client.post(
            "/v1/reseller/auth/login",
            headers={"Origin": capacity.portal_origin},
            json={"username": username, "password": password},
        )
        self.assertEqual(result.status_code, 200)
        return client, {
            "Origin": capacity.portal_origin,
            "X-CSRF-Token": result.json()["csrf_token"],
        }

    async def revise(self, reseller, **changes):
        current = (await self.get(f"/v1/admin/resellers/{reseller['id']}"))[
            "data"
        ]
        body = {
            "expected_revision": current["revision"],
            "title": current["title"],
            "access": {
                key: current[key]
                for key in (
                    "login_enabled",
                    "sales_enabled",
                    "renewals_enabled",
                )
            },
            "policy": current["policy"],
            "reason": "تغییر برای بررسی نمایندگی",
            **changes,
        }
        result = await self.client.put(
            f"/v1/admin/resellers/{reseller['id']}",
            headers=self.headers,
            json=body,
        )
        return result

    async def test_atomic_registration_realms_owned_customers_and_paging(self):
        first = await self.organization()
        second = await self.organization()
        a, ah = await self.login_reseller(first["owner"]["username"].upper())
        b, bh = await self.login_reseller(second["owner"]["username"])
        try:
            capacity = self.settings.resellers
            assert capacity is not None

            token = a.cookies.get("papilio_reseller")
            assert token is not None

            async def counterfeit(cookie, path):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=self.app),
                    base_url=capacity.portal_origin,
                    cookies={cookie: token},
                ) as client:
                    result = await client.get(path)
                    return result.status_code

            copied_tokens = await asyncio.gather(
                counterfeit("papilio_admin", "/v1/admin/auth/me"),
                counterfeit("papilio_customer", "/v1/customer/auth/me"),
            )
            self.assertEqual(copied_tokens, [401, 401])
            duplicate_owner = await self.client.post(
                "/v1/admin/resellers",
                headers=self.headers,
                json={
                    "code": "rollback_" + self.suffix,
                    "title": "برگشت ثبت",
                    "owner": {
                        "username": first["owner"]["username"],
                        "password": "dealer888",
                    },
                },
            )
            self.assertEqual(duplicate_owner.status_code, 409)
            wrong_realms = await asyncio.gather(
                *(
                    client.get(path)
                    for client in [a, b]
                    for path in (
                        "/v1/admin/auth/me",
                        "/v1/customer/auth/me",
                    )
                )
            )
            self.assertTrue(
                all(reply.status_code == 401 for reply in wrong_realms)
            )
            self.assertEqual(
                (await self.client.get("/v1/reseller/auth/me")).status_code,
                401,
            )
            created = await a.post(
                "/v1/reseller/customers",
                headers=ah,
                json={
                    "display_name": "مشتری انتخابی",
                    "telegram_id": int(self.suffix, 16),
                    "reseller_id": second["reseller"]["id"],
                },
            )
            self.assertEqual(created.status_code, 200)
            customer = created.json()["data"]
            denied = await b.get(f"/v1/reseller/customers/{customer['id']}")
            self.assertEqual(denied.status_code, 404)
            denied = await b.patch(
                f"/v1/reseller/customers/{customer['id']}",
                headers=bh,
                json={"display_name": "تغییر غیرمجاز"},
            )
            self.assertEqual(denied.status_code, 404)
            self.assertEqual(
                (
                    await a.post(
                        "/v1/reseller/customers",
                        json={"display_name": "بدون مجوز نوشتن"},
                    )
                ).status_code,
                403,
            )
            duplicate = await b.post(
                "/v1/reseller/customers",
                headers=bh,
                json={
                    "display_name": "تکراری",
                    "telegram_id": int(self.suffix, 16),
                },
            )
            self.assertEqual(duplicate.status_code, 409)
            self.assertEqual(
                (await b.get("/v1/reseller/customers")).json()["data"], []
            )
            extra = await a.post(
                "/v1/reseller/customers",
                headers=ah,
                json={"display_name": "مشتری دوم"},
            )
            self.assertEqual(extra.status_code, 200)
            one = await a.get("/v1/reseller/customers?per_page=1")
            two = await a.get("/v1/reseller/customers?per_page=1&page=2")
            self.assertEqual(one.json()["meta"]["pager"]["total_items"], 2)
            self.assertNotEqual(
                one.json()["data"][0]["id"], two.json()["data"][0]["id"]
            )
            async with self.connection.uow() as unit:
                count = (
                    await unit.execute(
                        text(
                            "SELECT COUNT(*) FROM tbl_reseller_customers "
                            "WHERE reseller_id=:id"
                        ),
                        {"id": first["reseller"]["id"]},
                    )
                ).scalar_one()
                self.assertEqual(count, 2)
                wallet_effects = (
                    await unit.execute(
                        text("SELECT COUNT(*) FROM tbl_wallet_entries")
                    )
                ).scalar_one()
                self.assertEqual(wallet_effects, 0)
                organizations = (
                    await unit.execute(
                        text("SELECT COUNT(*) FROM tbl_resellers")
                    )
                ).scalar_one()
                customers = (
                    await unit.execute(
                        text("SELECT COUNT(*) FROM tbl_customers")
                    )
                ).scalar_one()
                self.assertEqual((organizations, customers), (2, 4))
        finally:
            await asyncio.gather(a.aclose(), b.aclose())

    async def test_session_modes_delegation_revisions_and_password_revocation(
        self,
    ):
        defaults = (await self.get("/v1/admin/resellers/defaults"))["data"]
        policy = {
            **defaults["policy"],
            "max_sessions_per_account": 2,
            "session_limit_mode": "reject_new",
        }
        created = await self.organization(policy=policy)
        reseller = created["reseller"]
        username = created["owner"]["username"]
        a, _ = await self.login_reseller(username)
        b, _ = await self.login_reseller(username)
        capacity = self.settings.resellers
        assert capacity is not None
        rejected = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url=capacity.portal_origin,
        )
        c = reader = None
        try:
            third = await rejected.post(
                "/v1/reseller/auth/login",
                headers={"Origin": capacity.portal_origin},
                json={"username": username, "password": "dealer888"},
            )
            self.assertEqual(third.status_code, 409)
            policy.update(
                max_sessions_per_account=1, session_limit_mode="replace_oldest"
            )
            self.assertEqual(
                (await self.revise(reseller, policy=policy)).status_code, 200
            )
            c, ch = await self.login_reseller(username)
            old = await asyncio.gather(
                a.get("/v1/reseller/auth/me"), b.get("/v1/reseller/auth/me")
            )
            self.assertTrue(all(result.status_code == 401 for result in old))
            scopes = [
                "customers:read",
                "team:read",
                "team:create",
                "team:update",
                "team:manage",
            ]
            member = await c.post(
                "/v1/reseller/accounts",
                headers=ch,
                json={
                    "username": "reader_" + self.suffix,
                    "password": "reader888",
                    "is_active": True,
                    "scopes": scopes,
                },
            )
            self.assertEqual(member.status_code, 200)
            account = member.json()["data"]
            reader, rh = await self.login_reseller(
                account["username"], "reader888"
            )
            denied = await reader.post(
                "/v1/reseller/accounts",
                headers=rh,
                json={
                    "username": "forbidden_" + self.suffix,
                    "password": "reader888",
                    "is_active": True,
                    "scopes": ["*"],
                },
            )
            self.assertEqual(denied.status_code, 403)
            denied = await reader.post(
                "/v1/reseller/customers",
                headers=rh,
                json={"display_name": "بدون دسترسی ساخت"},
            )
            self.assertEqual(denied.status_code, 403)
            changed = await c.put(
                f"/v1/reseller/accounts/{account['id']}",
                headers=ch,
                json={
                    "expected_revision": account["revision"],
                    "is_active": True,
                    "scopes": ["customers:read"],
                    "reason": "کاهش دسترسی",
                },
            )
            self.assertEqual(changed.status_code, 200)
            self.assertEqual(
                (await reader.get("/v1/reseller/auth/me")).status_code, 401
            )
            stale = await c.put(
                f"/v1/reseller/accounts/{account['id']}",
                headers=ch,
                json={
                    "expected_revision": account["revision"],
                    "is_active": False,
                    "scopes": [],
                    "reason": "ویرایش قدیمی",
                },
            )
            self.assertEqual(stale.status_code, 409)
            owner = created["owner"]
            last_owner = await c.put(
                f"/v1/reseller/accounts/{owner['id']}",
                headers=ch,
                json={
                    "expected_revision": owner["revision"],
                    "is_active": False,
                    "scopes": [],
                    "reason": "حذف آخرین مدیر",
                },
            )
            self.assertEqual(last_owner.status_code, 409)
            reset = await self.client.put(
                f"/v1/admin/resellers/{reseller['id']}/accounts/{owner['id']}/password",
                headers=self.headers,
                json={
                    "expected_revision": owner["revision"],
                    "password": "newdealer888",
                    "reason": "تغییر رمز نمایندگی",
                },
            )
            self.assertEqual(reset.status_code, 200)
            self.assertEqual(
                (await c.get("/v1/reseller/auth/me")).status_code, 401
            )
            denied = await rejected.post(
                "/v1/reseller/auth/login",
                headers={"Origin": capacity.portal_origin},
                json={"username": username, "password": "dealer888"},
            )
            self.assertEqual(denied.status_code, 401)
            fresh, _ = await self.login_reseller(username, "newdealer888")
            try:
                history = await self.get(
                    f"/v1/admin/resellers/{reseller['id']}/accounts/{owner['id']}/history?per_page=1"
                )
                self.assertEqual(history["meta"]["pager"]["total_items"], 2)
                self.assertEqual(history["data"][0]["action"], "password")
                self.assertNotIn("password_hash", str(history))
                access = {
                    "login_enabled": False,
                    "sales_enabled": True,
                    "renewals_enabled": True,
                }
                self.assertEqual(
                    (await self.revise(reseller, access=access)).status_code,
                    200,
                )
                self.assertEqual(
                    (await fresh.get("/v1/reseller/auth/me")).status_code, 401
                )
                access["login_enabled"] = True
                self.assertEqual(
                    (await self.revise(reseller, access=access)).status_code,
                    200,
                )
                self.assertEqual(
                    (await fresh.get("/v1/reseller/auth/me")).status_code, 401
                )
            finally:
                await fresh.aclose()
        finally:
            clients = [a, b, rejected] + [
                client for client in [c, reader] if client is not None
            ]
            await asyncio.gather(*(client.aclose() for client in clients))

    async def test_concurrent_capacity_policy_tightening_and_parent_boundaries(
        self,
    ):
        defaults = (await self.get("/v1/admin/resellers/defaults"))["data"]
        policy = {
            **defaults["policy"],
            "customer_capacity": 1,
            "account_capacity": 2,
        }
        created = await self.organization(policy=policy)
        foreign = await self.organization()
        client, headers = await self.login_reseller(
            created["owner"]["username"]
        )
        reseller = created["reseller"]
        try:
            results = await asyncio.gather(
                *(
                    asyncio.create_task(
                        client.post(
                            "/v1/reseller/customers",
                            headers=headers,
                            json={"display_name": f"مشتری هم‌زمان {index}"},
                        ),
                        context=Context(),
                    )
                    for index in range(2)
                )
            )
            self.assertEqual(
                sorted(result.status_code for result in results), [200, 409]
            )
            memberships = await asyncio.gather(
                *(
                    asyncio.create_task(
                        client.post(
                            "/v1/reseller/accounts",
                            headers=headers,
                            json={
                                "username": f"member_{index}_{self.suffix}",
                                "password": "member888",
                                "is_active": True,
                                "scopes": ["customers:read"],
                            },
                        ),
                        context=Context(),
                    )
                    for index in range(2)
                )
            )
            self.assertEqual(
                sorted(result.status_code for result in memberships),
                [200, 409],
            )
            denied = await client.get(
                f"/v1/reseller/accounts/{foreign['owner']['id']}/history"
            )
            self.assertEqual(denied.status_code, 404)
            bad_parent = await self.client.get(
                f"/v1/admin/resellers/{reseller['id']}/accounts/{foreign['owner']['id']}"
            )
            self.assertEqual(bad_parent.status_code, 404)
            missing = await self.client.get(
                "/v1/admin/resellers/9223372036854775807/accounts"
            )
            self.assertEqual(missing.status_code, 404)
            capacity = self.settings.resellers
            assert capacity is not None
            capacity.max_customers_per_reseller = 1
            too_large = {**policy, "customer_capacity": 2}
            self.assertEqual(
                (await self.revise(reseller, policy=too_large)).status_code,
                400,
            )
            off = {
                "login_enabled": False,
                "sales_enabled": False,
                "renewals_enabled": False,
            }
            self.assertEqual(
                (
                    await self.revise(reseller, policy=too_large, access=off)
                ).status_code,
                200,
            )
            self.assertEqual(
                (await client.get("/v1/reseller/auth/me")).status_code, 401
            )
            self.assertEqual(
                (
                    await self.revise(
                        reseller,
                        policy=policy,
                        access={key: True for key in off},
                    )
                ).status_code,
                200,
            )
            fresh, fresh_headers = await self.login_reseller(
                created["owner"]["username"]
            )
            try:
                override = await fresh.post(
                    "/v1/reseller/customers",
                    headers=fresh_headers,
                    json={
                        "display_name": "تغییر ممنوع دسترسی",
                        "access": {
                            "is_active": False,
                            "services_enabled": False,
                            "renewals_enabled": False,
                        },
                    },
                )
                self.assertEqual(override.status_code, 409)
                self.assertEqual(
                    override.json()["error"]["message_code"],
                    "reseller_customer_access_denied",
                )
                async with self.connection.uow() as unit:
                    count = (
                        await unit.execute(
                            text(
                                "SELECT COUNT(*) FROM tbl_reseller_customers "
                                "WHERE reseller_id=:id"
                            ),
                            {"id": reseller["id"]},
                        )
                    ).scalar_one()
                    self.assertEqual(count, 1)
            finally:
                await fresh.aclose()
        finally:
            await client.aclose()

    async def test_owned_customer_access_actor_replay_policy_and_privacy(self):
        first = await self.organization()
        second = await self.organization()
        a, ah = await self.login_reseller(first["owner"]["username"])
        b, bh = await self.login_reseller(second["owner"]["username"])
        try:
            created = await a.post(
                "/v1/reseller/customers",
                headers=ah,
                json={"display_name": "مشتری دسترسی"},
            )
            self.assertEqual(created.status_code, 200)
            customer = created.json()["data"]
            policy = dict(first["reseller"]["policy"])
            policy["customer_access_override_enabled"] = True
            self.assertEqual(
                (
                    await self.revise(first["reseller"], policy=policy)
                ).status_code,
                200,
            )
            plan = await self.post(
                "/v1/admin/plans",
                {
                    "code": "access_" + self.suffix,
                    "title": "پلن دسترسی",
                    "price_rial": 80000,
                    "quota_bytes": 1000000,
                    "duration_days": 30,
                },
            )
            activation = await self.client.patch(
                f"/v1/admin/plans/{plan['id']}/active",
                headers=self.headers,
                json={"is_active": True},
            )
            self.assertEqual(activation.status_code, 200)
            await self.post(
                f"/v1/admin/resellers/{first['reseller']['id']}/plans",
                {
                    "plan_id": plan["id"],
                    "enabled": True,
                    "price": {
                        "mode": "catalog",
                        "rounding": "floor",
                        "quantum_rial": 1,
                    },
                    "reason": "قرارداد آزمون توقف",
                },
            )
            topup = await self.post(
                "/v1/admin/payments/topups",
                {
                    "customer_id": first["reseller"]["wallet_customer_id"],
                    "amount_rial": 100000,
                },
            )
            await self.post(
                f"/v1/admin/payments/topups/{topup['id']}/approve",
                {"expected_revision": 1, "bank_reference": uuid4().hex},
            )
            purchase = await a.post(
                "/v1/reseller/subscriptions",
                headers=ah,
                json={
                    "customer_id": customer["id"],
                    "plan_id": plan["id"],
                    "payer_mode": "reseller_wallet",
                    "purchase_key": uuid4().hex,
                    "expected_price_rial": 80000,
                },
            )
            self.assertEqual(purchase.status_code, 200)
            subscription = purchase.json()["data"]
            expected = {
                name: customer[name]
                for name in (
                    "is_active",
                    "services_enabled",
                    "renewals_enabled",
                )
            }
            body = {
                "request_key": uuid4().hex,
                "expected": expected,
                "values": {
                    "is_active": True,
                    "services_enabled": False,
                    "renewals_enabled": False,
                },
                "clock": "pause",
                "reason": "توقف با حساب واقعی نمایندگی",
            }
            path = f"/v1/reseller/customers/{customer['id']}/access"
            replies = await asyncio.gather(
                a.put(path, headers=ah, json=body),
                a.put(path, headers=ah, json=body),
            )
            self.assertEqual([r.status_code for r in replies], [200, 200])
            self.assertTrue(replies[0].json()["data"]["service_hold_pending"])
            from src.modules.sales.subscriptions.interfaces import (
                ICustomerHoldCommand,
            )

            async with self.app.state.dishka_container() as scope:
                command = await scope.get(ICustomerHoldCommand)
                held = await command.check(subscription["id"])
                self.assertEqual(held.status, "suspended")
            controls = (
                await self.get(
                    f"/v1/admin/subscriptions/{subscription['id']}/controls"
                )
            )["data"]
            self.assertEqual(len(controls), 1)
            self.assertIsNone(controls[0]["staff_id"])
            self.assertEqual(
                controls[0]["actor_account_id"], first["owner"]["id"]
            )
            denied = await b.put(path, headers=bh, json=body)
            self.assertEqual(denied.status_code, 404)
            self.assertEqual((await b.get(path + "-history")).status_code, 404)
            history = await a.get(path + "-history")
            self.assertEqual(history.status_code, 200)
            row = history.json()["data"][0]
            self.assertIsNone(row["staff_id"])
            self.assertEqual(row["reseller_id"], first["reseller"]["id"])
            self.assertEqual(row["actor_account_id"], first["owner"]["id"])
            staff_history = (
                await self.get(
                    f"/v1/admin/customers/{customer['id']}/access-history"
                )
            )["data"]
            self.assertEqual(staff_history, [row])
            async with self.connection.uow() as unit:
                persisted = (
                    await unit.execute(
                        text(
                            "SELECT staff_id, reseller_id, actor_account_id "
                            "FROM tbl_customer_access_changes "
                            "WHERE customer_id=:id"
                        ),
                        {"id": customer["id"]},
                    )
                ).all()
                self.assertEqual(
                    persisted,
                    [(None, first["reseller"]["id"], first["owner"]["id"])],
                )
                hold = (
                    await unit.execute(
                        text(
                            "SELECT service_hold_by_staff_id, "
                            "service_hold_by_reseller_account_id "
                            "FROM tbl_customers WHERE id=:id"
                        ),
                        {"id": customer["id"]},
                    )
                ).one()
                self.assertEqual(hold, (None, first["owner"]["id"]))
            policy["customer_access_override_enabled"] = False
            self.assertEqual(
                (
                    await self.revise(first["reseller"], policy=policy)
                ).status_code,
                200,
            )
            forbidden = await a.put(path, headers=ah, json=body)
            self.assertEqual(forbidden.status_code, 409)
            self.assertEqual(
                forbidden.json()["error"]["message_code"],
                "reseller_customer_access_denied",
            )
            self.assertEqual((await a.get(path + "-history")).status_code, 200)
        finally:
            await asyncio.gather(a.aclose(), b.aclose())

    async def test_populated_staff_access_history_survives_upgrade(self):
        import os
        from unittest.mock import patch

        from alembic import command
        from alembic.config import Config
        from sqlalchemy.engine import make_url

        customer = await self.post(
            "/v1/admin/customers", {"display_name": "تاریخچه قدیمی"}
        )
        expected = {
            name: customer[name]
            for name in ("is_active", "services_enabled", "renewals_enabled")
        }
        body = {
            "request_key": uuid4().hex,
            "expected": expected,
            "values": {
                "is_active": True,
                "services_enabled": False,
                "renewals_enabled": False,
            },
            "clock": "pause",
            "reason": "توقف قدیمی مدیر",
        }
        response = await self.client.put(
            f"/v1/admin/customers/{customer['id']}/access",
            headers=self.headers,
            json=body,
        )
        self.assertEqual(response.status_code, 200)
        path = f"/v1/admin/customers/{customer['id']}/access-history"
        before = (await self.get(path))["data"]
        self.assertEqual(len(before), 1)
        self.assertIsNotNone(before[0]["staff_id"])
        assert self.settings.db is not None
        config = Config("alembic.ini")
        config.set_main_option(
            "sqlalchemy.url",
            make_url(str(self.settings.db.dsn)).render_as_string(
                hide_password=False
            ),
        )
        with patch.dict(os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(
                command.downgrade, config, "0034_attention_payers"
            )
            await asyncio.to_thread(command.upgrade, config, "head")
        self.assertEqual((await self.get(path))["data"], before)
        stored = (await self.get(f"/v1/admin/customers/{customer['id']}"))[
            "data"
        ]
        self.assertFalse(stored["services_enabled"])
        self.assertTrue(stored["service_hold_pending"])
        self.assertEqual(
            (await self.client.get("/v1/admin/auth/me")).status_code, 200
        )
