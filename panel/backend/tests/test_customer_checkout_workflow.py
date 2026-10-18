import asyncio
from datetime import UTC, datetime, timedelta
from io import BytesIO

import httpx
from PIL import Image
from sqlalchemy import select, update
from sqlmodel import col
from starlette.middleware import Middleware

from src.config.middleware import RequestBodyLimitMiddleware
from src.modules.accounts.customer_auth.infra.tables import CustomerLoginTable
from src.modules.billing.receipts.infra.tables import PaymentReceiptTable
from tests.lock_observation import MySQLLockObservation
from tests.test_automation_workflow import AutomationWorkflowFixture


class CustomerCheckoutWorkflowTest(AutomationWorkflowFixture):
    async def account(self, telegram_id):
        headers = {"X-Papilio-Bot-Key": self.settings.security.bot_service_key}
        identity = {"telegram_id": telegram_id, "display_name": "مشتری مستقل"}
        linked = await self.client.post(
            "/v1/bot/account-link", headers=headers, json=identity
        )
        self.assertEqual(linked.status_code, 200)
        token = linked.json()["data"]["url"].rsplit("#", 1)[-1]
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url=self.settings.public.customer_portal_origin,
        )
        response = await client.post(
            "/v1/customer/auth/exchange",
            headers={"Origin": self.settings.public.customer_portal_origin},
            json={"token": token},
        )
        self.assertEqual(response.status_code, 200)
        session = response.json()
        replay = await client.post(
            "/v1/customer/auth/exchange",
            headers={"Origin": self.settings.public.customer_portal_origin},
            json={"token": token},
        )
        self.assertEqual(replay.status_code, 401)
        return (
            client,
            {
                "Origin": self.settings.public.customer_portal_origin,
                "X-CSRF-Token": session["csrf_token"],
            },
            session,
        )

    async def test_snapshot_private_receipts_review_and_customer_boundaries(
        self,
    ):
        destination = {
            "title": "کارت " + self.suffix,
            "kind": "card",
            "account": "6037990000000001",
            "recipient": "گیرنده",
            "bank_name": "بانک",
            "instructions": "شناسه را نگه دارید",
            "is_active": True,
        }
        row = await self.post("/v1/admin/payments/destinations", destination)
        prefs = (await self.get("/v1/admin/settings"))["data"]
        prefs["values"]["checkout"] = {
            **self.raw["checkout"]["policy"],
            "destination_mode": "required",
            "minimum_topup_rial": 1000,
            "maximum_topup_rial": 1000000,
        }
        saved = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": prefs["revision"],
                "values": prefs["values"],
            },
        )
        self.assertEqual(saved.status_code, 200)
        first, headers, identity = await self.account(
            1000000000 + int(self.suffix[:6], 16)
        )
        second, other_headers, other = await self.account(
            2000000000 + int(self.suffix[:6], 16)
        )
        try:
            missing = await first.post(
                "/v1/customer/topups",
                headers=headers,
                json={
                    "request_key": "checkout_" + self.suffix,
                    "amount_rial": 100000,
                },
            )
            self.assertEqual(missing.status_code, 409)
            payload = {
                "request_key": "checkout_" + self.suffix,
                "amount_rial": 100000,
                "destination_id": row["destination_id"],
            }
            attempts = await asyncio.gather(
                first.post(
                    "/v1/customer/topups", headers=headers, json=payload
                ),
                first.post(
                    "/v1/customer/topups", headers=headers, json=payload
                ),
            )
            self.assertTrue(all(r.status_code in (200, 409) for r in attempts))
            success = next(r for r in attempts if r.status_code == 200)
            tid = success.json()["data"]["id"]
            replay = await first.post(
                "/v1/customer/topups", headers=headers, json=payload
            )
            self.assertEqual(replay.json()["data"]["id"], tid)
            conflict = await first.post(
                "/v1/customer/topups",
                headers=headers,
                json={**payload, "amount_rial": 110000},
            )
            self.assertEqual(conflict.status_code, 409)
            badcsrf = await first.post(
                "/v1/customer/topups",
                json={**payload, "request_key": "different_key"},
            )
            self.assertEqual(badcsrf.status_code, 403)
            staff = await first.get("/v1/admin/payments/topups")
            self.assertEqual(staff.status_code, 401)
            await self.client.put(
                f"/v1/admin/payments/destinations/{row['destination_id']}",
                headers=self.headers,
                json={
                    **destination,
                    "account": "6037990000000002",
                    "is_active": False,
                },
            )
            instructions = await first.get(
                f"/v1/customer/topups/{tid}/instruction"
            )
            self.assertEqual(
                instructions.json()["data"][0]["account"],
                destination["account"],
            )
            unseen = await second.get(f"/v1/customer/topups/{tid}/instruction")
            self.assertEqual(unseen.status_code, 404)
            buffer = BytesIO()
            Image.new("RGB", (32, 32), "blue").save(buffer, format="PNG")
            original = buffer.getvalue()
            badimage = await first.post(
                f"/v1/customer/topups/{tid}/receipts",
                headers=headers,
                files={
                    "file": (
                        "receipt.png",
                        b"<script>receipt</script>",
                        "image/png",
                    )
                },
            )
            self.assertEqual(badimage.status_code, 409)
            upload = await first.post(
                f"/v1/customer/topups/{tid}/receipts",
                headers=headers,
                files={"file": ("receipt.png", original, "image/png")},
            )
            self.assertEqual(upload.status_code, 200)
            rid = upload.json()["data"]["id"]
            repeat = await first.post(
                f"/v1/customer/topups/{tid}/receipts",
                headers=headers,
                files={"file": ("receipt.png", original, "image/png")},
            )
            self.assertEqual(repeat.json()["data"]["id"], rid)
            private = await second.get(
                f"/v1/customer/topups/{tid}/receipts/{rid}"
            )
            self.assertEqual(private.status_code, 404)
            image = await first.get(
                f"/v1/customer/topups/{tid}/receipts/{rid}"
            )
            self.assertEqual(image.status_code, 200)
            self.assertEqual(image.headers["content-type"], "image/jpeg")
            self.assertTrue(image.content.startswith(b"\xff\xd8"))
            async with self.connection.uow() as independent:
                stored = (
                    await independent.execute(
                        select(PaymentReceiptTable).where(
                            col(PaymentReceiptTable.id) == rid
                        )
                    )
                ).scalar_one()
                self.assertNotIn("/9j/", stored.encrypted_payload)
                self.assertNotIn("encrypted_payload", upload.json()["data"])
            balance = await first.get("/v1/customer/wallet")
            self.assertEqual(balance.json()["data"]["balance_rial"], 0)
            reviewed = await self.post(
                f"/v1/admin/payments/topups/{tid}/approve",
                {
                    "expected_revision": 1,
                    "bank_reference": "bank_" + self.suffix,
                },
            )
            self.assertEqual(reviewed["status"], "approved")
            await self.post(
                f"/v1/admin/payments/topups/{tid}/approve",
                {
                    "expected_revision": 1,
                    "bank_reference": "bank_" + self.suffix,
                },
            )
            balance = await first.get("/v1/customer/wallet")
            self.assertEqual(balance.json()["data"]["balance_rial"], 100000)
            ledger = await first.get("/v1/customer/wallet/entries")
            self.assertEqual(ledger.json()["meta"]["pager"]["total_items"], 1)
            self.assertEqual(
                (await second.get("/v1/customer/wallet")).json()["data"][
                    "balance_rial"
                ],
                0,
            )
            self.assertNotEqual(identity["customer_id"], other["customer_id"])
            await first.post("/v1/customer/auth/logout", headers=headers)
            self.assertEqual(
                (await first.get("/v1/customer/wallet")).status_code, 401
            )
        finally:
            current = (await self.get("/v1/admin/settings"))["data"]
            current["values"]["checkout"] = self.raw["checkout"]["policy"]
            restored = await self.client.put(
                "/v1/admin/settings",
                headers=self.headers,
                json={
                    "expected_revision": current["revision"],
                    "values": current["values"],
                },
            )
            self.assertEqual(restored.status_code, 200)
            await first.aclose()
            await second.aclose()

    async def test_expired_login_and_dynamic_upload_body_budget(self):
        from papilio.api.application import create_app

        from src.config.providers import infrastructure_providers

        app = create_app(
            self.settings,
            providers=infrastructure_providers(self.settings),
            middleware=[
                Middleware(
                    RequestBodyLimitMiddleware,
                    max_bytes=128,
                    receipt_bytes=self.settings.receipts.max_request_bytes,
                )
            ],
            docs_url=None,
        )
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=self.settings.public.customer_portal_origin,
        )
        try:
            json_overflow = await client.post(
                "/v1/customer/auth/exchange", content=b" " * 129
            )
            self.assertEqual(json_overflow.status_code, 413)
            # Receipt metadata permits larger bodies; auth still denies access.
            upload = await client.post(
                "/v1/customer/topups/1/receipts",
                files={"file": ("x.png", b"x" * 129, "image/png")},
            )
            self.assertEqual(upload.status_code, 401)
            too_large = await client.post(
                "/v1/customer/topups/1/receipts",
                headers={
                    "Content-Length": str(
                        self.settings.receipts.max_request_bytes + 1
                    )
                },
                content=b"",
            )
            self.assertEqual(too_large.status_code, 413)
            linked = await self.client.post(
                "/v1/bot/account-link",
                headers={
                    "X-Papilio-Bot-Key": self.settings.security.bot_service_key
                },
                json={
                    "telegram_id": 3000000000 + int(self.suffix[:6], 16),
                    "display_name": "حساب",
                },
            )
            token = linked.json()["data"]["url"].rsplit("#", 1)[-1]
            from papilio.security.crypto import hash_sha256

            async with self.connection.uow() as independent:
                await independent.execute(
                    update(CustomerLoginTable)
                    .where(
                        col(CustomerLoginTable.token_hash)
                        == hash_sha256(token)
                    )
                    .values(
                        expires_at=datetime.now(UTC).replace(tzinfo=None)
                        - timedelta(seconds=1)
                    )
                )
                await independent.commit()
            expired = await self.client.post(
                "/v1/customer/auth/exchange",
                headers={
                    "Origin": self.settings.public.customer_portal_origin
                },
                json={"token": token},
            )
            self.assertEqual(expired.status_code, 401)
        finally:
            await client.aclose()
            await app.state.dishka_container.close()

    async def test_receipt_capacity_with_concurrent_authenticated_snapshots(
        self,
    ):

        from src.modules.billing.wallet.infra.tables import TopupTable

        current = (await self.get("/v1/admin/settings"))["data"]
        current["values"]["checkout"] = self.raw["checkout"]["policy"]
        await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": current["revision"],
                "values": current["values"],
            },
        )
        self.settings.receipts.max_per_topup = 1
        current = (await self.get("/v1/admin/settings"))["data"]
        current["values"]["receipts"]["max_per_topup"] = 1
        changed = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": current["revision"],
                "values": current["values"],
            },
        )
        self.assertEqual(changed.status_code, 200)
        client, headers, identity = await self.account(
            4000000000 + int(self.suffix[:6], 16)
        )
        try:
            topup = await client.post(
                "/v1/customer/topups",
                headers=headers,
                json={
                    "request_key": "race_" + self.suffix,
                    "amount_rial": 10000,
                },
            )
            self.assertEqual(topup.status_code, 200)
            tid = topup.json()["data"]["id"]
            one = BytesIO()
            Image.new("RGB", (32, 32), "red").save(one, format="PNG")
            two = BytesIO()
            Image.new("RGB", (32, 32), "green").save(two, format="PNG")
            async with self.connection.uow() as holder:
                await holder.execute(
                    select(TopupTable)
                    .where(col(TopupTable.id) == tid)
                    .with_for_update()
                )
                a = asyncio.create_task(
                    client.post(
                        f"/v1/customer/topups/{tid}/receipts",
                        headers=headers,
                        files={"file": ("a.png", one.getvalue(), "image/png")},
                    )
                )
                b = asyncio.create_task(
                    client.post(
                        f"/v1/customer/topups/{tid}/receipts",
                        headers=headers,
                        files={"file": ("b.png", two.getvalue(), "image/png")},
                    )
                )
                try:
                    assert self.settings.db is not None
                    blocked = await asyncio.to_thread(
                        MySQLLockObservation().wait_for_queries,
                        self.settings.db.dsn,
                        "tbl_topups",
                        ("SELECT",),
                        2,
                        5,
                        0.025,
                        True,
                    )
                    self.assertTrue(
                        blocked, "Both uploads must wait on top-up"
                    )
                finally:
                    await holder.commit()
            results = await asyncio.gather(a, b)
            self.assertEqual(
                sorted(row.status_code for row in results), [200, 409]
            )
            committed = await client.get(f"/v1/customer/topups/{tid}/receipts")
            self.assertEqual(
                committed.json()["meta"]["pager"]["total_items"], 1
            )
            self.assertEqual(
                identity["customer_id"], topup.json()["data"]["customer_id"]
            )
        finally:
            self.settings.receipts.max_per_topup = self.raw["receipts"][
                "max_per_topup"
            ]
            current = (await self.get("/v1/admin/settings"))["data"]
            current["values"]["receipts"]["max_per_topup"] = self.raw[
                "receipts"
            ]["max_per_topup"]
            await self.client.put(
                "/v1/admin/settings",
                headers=self.headers,
                json={
                    "expected_revision": current["revision"],
                    "values": current["values"],
                },
            )
            await client.aclose()

    async def test_upgrade_preserves_settled_legacy_payments(self):
        import os
        import secrets
        from unittest.mock import patch

        import pymysql
        from alembic import command
        from alembic.config import Config
        from sqlalchemy.engine import make_url

        from tests.test_automation_workflow import TEST_URL

        database = "papilio_upgrade_test_" + secrets.token_hex(6)
        url = make_url(str(TEST_URL)).set(database=database)
        assert url.host == "127.0.0.1" and "test" in database
        assert url.username and url.password and url.host

        def connection(selected=None):
            assert url.username and url.password and url.host
            return pymysql.connect(
                host=url.host,
                port=url.port or 3306,
                user=url.username,
                password=url.password,
                database=selected,
                autocommit=True,
            )

        def migrate():
            config = Config("alembic.ini")
            config.set_main_option(
                "sqlalchemy.url", url.render_as_string(hide_password=False)
            )
            with connection() as server:
                with server.cursor() as cursor:
                    cursor.execute(f"CREATE DATABASE `{database}`")
            try:
                with patch.dict(
                    os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}
                ):
                    command.upgrade(config, "0020_usage_indexes")
                with connection(database) as db:
                    with db.cursor() as cursor:
                        cursor.execute(
                            "INSERT INTO tbl_staff "
                            "(id,username,password_hash,is_active) VALUES "
                            "(1,'legacy','unusable',1)"
                        )
                        cursor.execute(
                            "INSERT INTO tbl_customers "
                            "(id,display_name,is_active) VALUES "
                            "(1,'legacy',1)"
                        )
                        cursor.execute(
                            "INSERT INTO tbl_wallets "
                            "(id,customer_id,balance_rial) VALUES "
                            "(1,1,25000)"
                        )
                        cursor.execute(
                            "INSERT INTO tbl_topups "
                            "(id,customer_id,amount_rial,status,bank_reference,"
                            "approved_by_staff_id) "
                            "VALUES "
                            "(1,1,25000,'approved','legacy-settlement',1)"
                        )
                        cursor.execute(
                            "INSERT INTO tbl_wallet_entries "
                            "(id,wallet_id,amount_rial,balance_after_rial,"
                            "reference,reason) "
                            "VALUES "
                            "(1,1,25000,25000,'topup:1','approved_topup')"
                        )
                with patch.dict(
                    os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}
                ):
                    command.upgrade(config, "head")
                with connection(database) as db:
                    with db.cursor() as cursor:
                        cursor.execute(
                            "SELECT "
                            "amount_rial,status,bank_reference,request_key,"
                            "destination_id,encrypted_instruction "
                            "FROM tbl_topups WHERE id=1"
                        )
                        self.assertEqual(
                            cursor.fetchone(),
                            (
                                25000,
                                "approved",
                                "legacy-settlement",
                                None,
                                None,
                                None,
                            ),
                        )
                        cursor.execute(
                            "SELECT balance_rial FROM tbl_wallets WHERE id=1"
                        )
                        self.assertEqual(cursor.fetchone(), (25000,))
                        cursor.execute(
                            "SELECT COUNT(*) FROM tbl_wallet_entries"
                        )
                        self.assertEqual(cursor.fetchone(), (1,))
                        cursor.execute(
                            "SELECT COUNT(*) FROM tbl_payment_receipts"
                        )
                        self.assertEqual(cursor.fetchone(), (0,))
            finally:
                with connection() as server:
                    with server.cursor() as cursor:
                        cursor.execute(f"DROP DATABASE IF EXISTS `{database}`")

        await asyncio.to_thread(migrate)

    async def test_legacy_checkout_and_receipt_disable_recovery(self):
        client, headers, _ = await self.account(
            6000000000 + int(self.suffix[:6], 16)
        )
        try:
            destination = await self.post(
                "/v1/admin/payments/destinations",
                {
                    "title": "حساب " + self.suffix,
                    "kind": "bank_account",
                    "account": "account-" + self.suffix,
                    "recipient": "گیرنده",
                    "bank_name": "بانک",
                    "is_active": True,
                },
            )
            current = (await self.get("/v1/admin/settings"))["data"]
            current["values"]["checkout"] = {
                **self.raw["checkout"]["policy"],
                "destination_mode": "legacy",
            }
            current["values"]["receipts"]["enabled"] = False
            changed = await self.client.put(
                "/v1/admin/settings",
                headers=self.headers,
                json={
                    "expected_revision": current["revision"],
                    "values": current["values"],
                },
            )
            self.assertEqual(changed.status_code, 200)
            choices = await client.get("/v1/customer/payment-destinations")
            self.assertEqual(choices.json()["data"], [])
            payload = {
                "request_key": "legacy_" + self.suffix,
                "amount_rial": 10000,
            }
            request = await client.post(
                "/v1/customer/topups", headers=headers, json=payload
            )
            self.assertEqual(request.status_code, 200)
            tid = request.json()["data"]["id"]
            instructions = await client.get(
                f"/v1/customer/topups/{tid}/instruction"
            )
            self.assertEqual(instructions.json()["data"], [])
            unwanted = await client.post(
                "/v1/customer/topups",
                headers=headers,
                json={
                    **payload,
                    "request_key": "destination_" + self.suffix,
                    "destination_id": destination["destination_id"],
                },
            )
            self.assertEqual(unwanted.status_code, 409)
            image = BytesIO()
            Image.new("RGB", (32, 32), "blue").save(image, format="PNG")
            upload = await client.post(
                f"/v1/customer/topups/{tid}/receipts",
                headers=headers,
                files={"file": ("x.png", image.getvalue(), "image/png")},
            )
            self.assertEqual(upload.status_code, 409)
            current = (await self.get("/v1/admin/settings"))["data"]
            current["values"]["checkout"] = {
                **self.raw["checkout"]["policy"],
                "destination_mode": "required",
            }
            current["values"]["receipts"]["enabled"] = True
            await self.client.put(
                "/v1/admin/settings",
                headers=self.headers,
                json={
                    "expected_revision": current["revision"],
                    "values": current["values"],
                },
            )
            # Recovery replays the original request despite the new policy.
            replay = await client.post(
                "/v1/customer/topups", headers=headers, json=payload
            )
            self.assertEqual(replay.status_code, 200)
            self.assertEqual(replay.json()["data"]["id"], tid)
            uploaded = await client.post(
                f"/v1/customer/topups/{tid}/receipts",
                headers=headers,
                files={"file": ("x.png", image.getvalue(), "image/png")},
            )
            self.assertEqual(uploaded.status_code, 200)
            self.assertEqual(
                (await client.get("/v1/customer/wallet")).json()["data"][
                    "balance_rial"
                ],
                0,
            )
        finally:
            current = (await self.get("/v1/admin/settings"))["data"]
            current["values"]["checkout"] = self.raw["checkout"]["policy"]
            current["values"]["receipts"]["enabled"] = True
            await self.client.put(
                "/v1/admin/settings",
                headers=self.headers,
                json={
                    "expected_revision": current["revision"],
                    "values": current["values"],
                },
            )
            await client.aclose()

    async def test_changed_price_never_debits_and_paid_replay_keeps_quote(
        self,
    ):
        current = (await self.get("/v1/admin/settings"))["data"]
        current["values"]["checkout"] = self.raw["checkout"]["policy"]
        await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": current["revision"],
                "values": current["values"],
            },
        )
        client, headers, _ = await self.account(
            7000000000 + int(self.suffix[:6], 16)
        )
        try:
            plan = await self.post(
                "/v1/admin/plans",
                {
                    "code": "quote_" + self.suffix,
                    "title": "قیمت توافقی",
                    "quota_bytes": 1000000,
                    "duration_days": 30,
                    "price_rial": 10000,
                    "fulfillment": {
                        **self.raw["fulfillment"]["policy"],
                        "automatic": False,
                    },
                },
            )
            enabled = await self.client.patch(
                f"/v1/admin/plans/{plan['id']}/active",
                headers=self.headers,
                json={"is_active": True},
            )
            self.assertEqual(enabled.status_code, 200)
            quote = await client.get(f"/v1/customer/plans/{plan['id']}")
            self.assertEqual(quote.json()["data"]["price_rial"], 10000)
            topup = await client.post(
                "/v1/customer/topups",
                headers=headers,
                json={
                    "request_key": "fund_" + self.suffix,
                    "amount_rial": 100000,
                },
            )
            tid = topup.json()["data"]["id"]
            await self.post(
                f"/v1/admin/payments/topups/{tid}/approve",
                {
                    "expected_revision": 1,
                    "bank_reference": "quote_" + self.suffix,
                },
            )
            changed = await self.client.patch(
                f"/v1/admin/plans/{plan['id']}",
                headers=self.headers,
                json={"price_rial": 20000},
            )
            self.assertEqual(changed.status_code, 200)
            payload = {
                "purchase_key": "quote_" + self.suffix,
                "plan_id": plan["id"],
                "auto_renew": True,
                "expected_price_rial": 10000,
            }
            stale = await client.post(
                "/v1/customer/subscriptions", headers=headers, json=payload
            )
            self.assertEqual(stale.status_code, 409)
            self.assertEqual(
                (await client.get("/v1/customer/wallet")).json()["data"][
                    "balance_rial"
                ],
                100000,
            )
            quote = await client.get(f"/v1/customer/plans/{plan['id']}")
            payload["expected_price_rial"] = quote.json()["data"]["price_rial"]
            bought = await client.post(
                "/v1/customer/subscriptions", headers=headers, json=payload
            )
            self.assertEqual(bought.status_code, 200)
            sid = bought.json()["data"]["id"]
            self.assertEqual(bought.json()["data"]["price_rial"], 20000)
            await self.client.patch(
                f"/v1/admin/plans/{plan['id']}",
                headers=self.headers,
                json={"price_rial": 30000},
            )
            replay = await client.post(
                "/v1/customer/subscriptions", headers=headers, json=payload
            )
            self.assertEqual(replay.status_code, 200)
            self.assertEqual(replay.json()["data"]["id"], sid)
            self.assertEqual(
                (await client.get("/v1/customer/wallet")).json()["data"][
                    "balance_rial"
                ],
                80000,
            )
            ledger = await client.get("/v1/customer/wallet/entries")
            self.assertEqual(ledger.json()["meta"]["pager"]["total_items"], 2)
            conflicting = await client.post(
                "/v1/customer/subscriptions",
                headers=headers,
                json={**payload, "expected_price_rial": 30000},
            )
            self.assertEqual(conflicting.status_code, 200)
            self.assertEqual(conflicting.json()["data"]["id"], sid)
            self.assertEqual(
                (await client.get("/v1/customer/wallet")).json()["data"][
                    "balance_rial"
                ],
                80000,
            )
        finally:
            await client.aclose()

    async def test_non_ascii_authentication_headers_are_denied(self):
        invalid_bot = await self.client.post(
            "/v1/bot/home",
            headers=[(b"X-Papilio-Bot-Key", b"\xff")],
            json={"telegram_id": 1, "display_name": "نامعتبر"},
        )
        self.assertEqual(invalid_bot.status_code, 401)
        staff_headers = [
            (b"Origin", self.settings.public.admin_origin.encode("ascii")),
            (b"X-CSRF-Token", b"\xff"),
        ]
        invalid_staff = await self.client.post(
            "/v1/admin/payments/topups",
            headers=staff_headers,
            json={"customer_id": 1, "amount_rial": 10000},
        )
        self.assertEqual(invalid_staff.status_code, 403)
        client, _, _ = await self.account(
            8000000000 + int(self.suffix[:6], 16)
        )
        try:
            invalid_customer = await client.post(
                "/v1/customer/topups",
                headers=[
                    (
                        b"Origin",
                        self.settings.public.customer_portal_origin.encode(
                            "ascii"
                        ),
                    ),
                    (b"X-CSRF-Token", b"\xff"),
                ],
                json={
                    "request_key": "denied_" + self.suffix,
                    "amount_rial": 10000,
                },
            )
            self.assertEqual(invalid_customer.status_code, 403)
        finally:
            await client.aclose()
