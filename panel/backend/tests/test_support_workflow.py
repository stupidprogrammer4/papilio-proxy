import asyncio
import json
import os
from contextvars import Context
from unittest.mock import patch
from uuid import uuid4

import httpx
from alembic import command
from alembic.config import Config
from papilio.infra.db.transaction import transaction
from sqlalchemy import text, update
from sqlalchemy.engine import make_url

from src.modules.operations.preferences.infra.tables import (
    PreferencesRevisionTable,
)
from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowTest,
)


class SupportWorkflowTest(StaffAdministrationWorkflowTest):
    async def account(self):
        identity = {
            "telegram_id": int(uuid4().hex[:12], 16),
            "display_name": "مشتری پشتیبانی",
        }
        linked = await self.client.post(
            "/v1/bot/account-link",
            headers={
                "X-Papilio-Bot-Key": self.settings.security.bot_service_key
            },
            json=identity,
        )
        self.assertEqual(linked.status_code, 200)
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url=self.settings.public.customer_portal_origin,
        )
        response = await client.post(
            "/v1/customer/auth/exchange",
            headers={"Origin": self.settings.public.customer_portal_origin},
            json={"token": linked.json()["data"]["url"].rsplit("#", 1)[-1]},
        )
        self.assertEqual(response.status_code, 200)
        session = response.json()
        return (
            client,
            {
                "Origin": self.settings.public.customer_portal_origin,
                "X-CSRF-Token": session["csrf_token"],
            },
            session["customer_id"],
        )

    async def policy(self, **changes):
        prefs = (await self.get("/v1/admin/settings"))["data"]
        prefs["values"]["support"].update(changes)
        result = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": prefs["revision"],
                "values": prefs["values"],
            },
        )
        self.assertEqual(result.status_code, 200)
        return result.json()["data"]

    async def test_private_threads_replays_policy_modes_and_scoped_staff(self):
        first, headers, customer_id = await self.account()
        other, other_headers, other_id = await self.account()
        try:
            payload = dict(
                request_key=uuid4().hex,
                subject="مشکل اتصال",
                body="<script>محتوای متنی</script>",
                customer_id=other_id,
            )
            created = await first.post(
                "/v1/customer/support", headers=headers, json=payload
            )
            self.assertEqual(created.status_code, 200)
            ticket = created.json()["data"]
            self.assertEqual(ticket["customer_id"], customer_id)
            self.assertNotIn("creation_hash", ticket)
            self.assertEqual(
                (
                    await first.post(
                        "/v1/customer/support", headers=headers, json=payload
                    )
                ).json()["data"]["id"],
                ticket["id"],
            )
            changed = await first.post(
                "/v1/customer/support",
                headers=headers,
                json={**payload, "body": "متن دیگری"},
            )
            self.assertEqual(changed.status_code, 409)
            private_reads = await asyncio.gather(
                *(
                    other.get(path)
                    for path in [
                        f"/v1/customer/support/{ticket['id']}",
                        f"/v1/customer/support/{ticket['id']}/messages",
                        f"/v1/customer/support/{ticket['id']}/history",
                    ]
                )
            )
            for response in private_reads:
                self.assertEqual(response.status_code, 404)
            forged_reply = await other.post(
                f"/v1/customer/support/{ticket['id']}/messages",
                headers=other_headers,
                json=dict(
                    request_key=uuid4().hex,
                    expected_revision=1,
                    body="تلاش حساب دیگر",
                ),
            )
            self.assertEqual(forged_reply.status_code, 404)
            forged_state = await other.put(
                f"/v1/customer/support/{ticket['id']}/state",
                headers=other_headers,
                json=dict(
                    expected_revision=1,
                    status="closed",
                    reason="تلاش حساب دیگر",
                ),
            )
            self.assertEqual(forged_state.status_code, 404)
            page = await other.get(
                "/v1/customer/support", params={"customer_id": customer_id}
            )
            self.assertEqual(page.json()["data"], [])
            self.assertEqual(
                (await self.client.get("/v1/customer/support")).status_code,
                401,
            )
            self.assertEqual(
                (await first.get("/v1/admin/support")).status_code, 401
            )
            self.assertEqual(
                (
                    await first.post(
                        f"/v1/customer/support/{ticket['id']}/messages",
                        json=dict(
                            request_key=uuid4().hex,
                            expected_revision=1,
                            body="بدون اعتبار",
                        ),
                    )
                ).status_code,
                403,
            )
            staff = await self.post(
                "/v1/admin/staff",
                dict(
                    username="support_" + self.suffix,
                    password="staff888",
                    is_active=True,
                    scopes=["support:read", "support:update"],
                ),
            )
            staff_client, staff_headers = await self.login_staff(
                staff["username"], "staff888"
            )
            try:
                self.assertEqual(
                    (
                        await staff_client.post(
                            "/v1/admin/support",
                            headers=staff_headers,
                            json={**payload, "customer_id": customer_id},
                        )
                    ).status_code,
                    403,
                )
                reply_payload = dict(
                    request_key=uuid4().hex,
                    expected_revision=1,
                    body="پاسخ پشتیبانی",
                )
                reply = await staff_client.post(
                    f"/v1/admin/support/{ticket['id']}/messages",
                    headers=staff_headers,
                    json=reply_payload,
                )
                self.assertEqual(reply.status_code, 200)
                ticket = reply.json()["data"]
                self.assertEqual(ticket["status"], "waiting_customer")
                replay = await staff_client.post(
                    f"/v1/admin/support/{ticket['id']}/messages",
                    headers=staff_headers,
                    json=reply_payload,
                )
                self.assertEqual(replay.status_code, 200)
                history = await staff_client.get(
                    f"/v1/admin/support/{ticket['id']}/history?per_page=1"
                )
                self.assertEqual(
                    history.json()["data"][0]["staff_id"], staff["id"]
                )
            finally:
                await staff_client.aclose()
            closed = await first.put(
                f"/v1/customer/support/{ticket['id']}/state",
                headers=headers,
                json=dict(
                    expected_revision=ticket["revision"],
                    status="closed",
                    reason="مشکل حل شد",
                ),
            )
            self.assertEqual(closed.status_code, 200)
            ticket = closed.json()["data"]
            reply_payload = dict(
                request_key=uuid4().hex,
                expected_revision=ticket["revision"],
                body="مشکل تازه",
            )
            self.assertEqual(
                (
                    await first.post(
                        f"/v1/customer/support/{ticket['id']}/messages",
                        headers=headers,
                        json=reply_payload,
                    )
                ).status_code,
                409,
            )
            await self.policy(
                closed_reply_mode="reopen", max_messages_per_ticket=3
            )
            reopened = await first.post(
                f"/v1/customer/support/{ticket['id']}/messages",
                headers=headers,
                json=reply_payload,
            )
            self.assertEqual(reopened.status_code, 200)
            ticket = reopened.json()["data"]
            self.assertEqual(ticket["status"], "open")
            self.assertEqual(
                (
                    await first.post(
                        f"/v1/customer/support/{ticket['id']}/messages",
                        headers=headers,
                        json=reply_payload,
                    )
                ).status_code,
                200,
            )
            full = await first.post(
                f"/v1/customer/support/{ticket['id']}/messages",
                headers=headers,
                json=dict(
                    request_key=uuid4().hex,
                    expected_revision=ticket["revision"],
                    body="بیش از ظرفیت",
                ),
            )
            self.assertEqual(full.status_code, 409)
            messages = (
                await first.get(
                    f"/v1/customer/support/{ticket['id']}/messages?per_page=1&page=3"
                )
            ).json()
            self.assertEqual(messages["meta"]["pager"]["total_items"], 3)
            self.assertEqual(messages["data"][0]["body"], payload["body"])
            self.assertNotIn("staff_id", messages["data"][0])
            history = (
                await first.get(
                    f"/v1/customer/support/{ticket['id']}/history?per_page=1"
                )
            ).json()
            self.assertEqual(history["meta"]["pager"]["total_items"], 3)
            self.assertNotIn("staff_id", history["data"][0])
            async with self.connection.uow() as unit:
                counts = await unit.execute(
                    text(
                        "SELECT (SELECT COUNT(*) FROM tbl_support_tickets), "
                        "(SELECT COUNT(*) FROM tbl_support_messages), "
                        "(SELECT COUNT(*) FROM tbl_support_state_changes)"
                    )
                )
                self.assertEqual(tuple(counts.one()), (1, 3, 3))
        finally:
            await first.aclose()
            await other.aclose()

    async def test_support_concurrency_capacities_stop_modes_and_context(self):
        client, headers, customer_id = await self.account()
        try:
            await self.policy(max_open_tickets=1, max_message_chars=40)
            first_body = dict(
                request_key=uuid4().hex, subject="درخواست اول", body="متن اول"
            )
            second_body = dict(
                request_key=uuid4().hex, subject="درخواست دوم", body="متن دوم"
            )
            requests = [
                asyncio.create_task(
                    client.post(
                        "/v1/customer/support", headers=headers, json=body
                    ),
                    context=Context(),
                )
                for body in [first_body, second_body]
            ]
            results = await asyncio.gather(*requests)
            self.assertEqual(
                sorted(result.status_code for result in results), [200, 409]
            )
            result = next(
                result for result in results if result.status_code == 200
            )
            ticket = result.json()["data"]
            replies = [
                asyncio.create_task(
                    client.post(
                        f"/v1/customer/support/{ticket['id']}/messages",
                        headers=headers,
                        json=dict(
                            request_key=uuid4().hex,
                            body=body,
                            expected_revision=1,
                        ),
                    ),
                    context=Context(),
                )
                for body in ["پاسخ اول", "پاسخ دوم"]
            ]
            results = await asyncio.gather(*replies)
            self.assertEqual(
                sorted(result.status_code for result in results), [200, 409]
            )
            ticket = next(
                result for result in results if result.status_code == 200
            ).json()["data"]
            await self.policy(
                new_tickets_enabled=False,
                customer_replies_enabled=False,
                customer_closure_enabled=False,
            )
            self.assertEqual(
                (
                    await client.post(
                        "/v1/customer/support",
                        headers=headers,
                        json=dict(
                            request_key=uuid4().hex,
                            subject="غیرفعال",
                            body="متن",
                        ),
                    )
                ).status_code,
                403,
            )
            self.assertEqual(
                (
                    await client.post(
                        f"/v1/customer/support/{ticket['id']}/messages",
                        headers=headers,
                        json=dict(
                            request_key=uuid4().hex,
                            expected_revision=ticket["revision"],
                            body="بسته",
                        ),
                    )
                ).status_code,
                403,
            )
            self.assertEqual(
                (
                    await client.put(
                        f"/v1/customer/support/{ticket['id']}/state",
                        headers=headers,
                        json=dict(
                            status="closed",
                            expected_revision=ticket["revision"],
                            reason="بستن مشتری",
                        ),
                    )
                ).status_code,
                403,
            )
            self.assertEqual(
                (
                    await client.get(
                        f"/v1/customer/support/{ticket['id']}/messages"
                    )
                ).status_code,
                200,
            )
            closed = await self.client.put(
                f"/v1/admin/support/{ticket['id']}/state",
                headers=self.headers,
                json=dict(
                    status="closed",
                    expected_revision=ticket["revision"],
                    reason="بستن مدیر",
                ),
            )
            self.assertEqual(closed.status_code, 200)
            ticket = closed.json()["data"]
            self.assertEqual(
                (
                    await client.put(
                        f"/v1/customer/support/{ticket['id']}/state",
                        headers=headers,
                        json=dict(
                            status="open",
                            expected_revision=ticket["revision"],
                            reason="بازگشایی مشتری",
                        ),
                    )
                ).status_code,
                403,
            )
            await self.policy(
                new_tickets_enabled=True,
                customer_replies_enabled=True,
                customer_reopen_enabled=True,
                staff_replies_enabled=False,
            )
            self.assertEqual(
                (
                    await self.client.post(
                        f"/v1/admin/support/{ticket['id']}/messages",
                        headers=self.headers,
                        json=dict(
                            request_key=uuid4().hex,
                            expected_revision=ticket["revision"],
                            body="پاسخ مدیر",
                        ),
                    )
                ).status_code,
                403,
            )
            self.assertEqual(
                (
                    await client.post(
                        "/v1/customer/support",
                        headers=headers,
                        json=dict(
                            request_key=uuid4().hex,
                            subject="طول نامعتبر",
                            body="🦋" * 41,
                        ),
                    )
                ).status_code,
                409,
            )
            _, other_subscription = await self.paid_subscription()
            wrong = await client.post(
                "/v1/customer/support",
                headers=headers,
                json=dict(
                    request_key=uuid4().hex,
                    subject="سرویس دیگری",
                    body="درخواست",
                    subscription_id=other_subscription["id"],
                ),
            )
            self.assertEqual(wrong.status_code, 409)
            topup = await self.post(
                "/v1/admin/payments/topups",
                dict(customer_id=customer_id, amount_rial=100000),
            )
            owned = await client.post(
                "/v1/customer/support",
                headers=headers,
                json=dict(
                    request_key=uuid4().hex,
                    subject="پرداخت خودم",
                    body="درخواست",
                    topup_id=topup["id"],
                ),
            )
            self.assertEqual(owned.status_code, 200)
            owned = owned.json()["data"]
            self.assertEqual(owned["topup_id"], topup["id"])
            prefs = (await self.get("/v1/admin/settings"))["data"]
            prefs["values"]["support"]["max_message_chars"] = (
                self.settings.support.max_message_chars + 1
            )
            denied = await self.client.put(
                "/v1/admin/settings",
                headers=self.headers,
                json=dict(
                    expected_revision=prefs["revision"], values=prefs["values"]
                ),
            )
            self.assertEqual(denied.status_code, 400)
            with patch.object(self.settings.support, "max_message_chars", 1):
                policy = (
                    await client.get("/v1/customer/support/policy")
                ).json()["data"]
                self.assertFalse(policy["capacity_valid"])
                denied = await client.post(
                    f"/v1/customer/support/{owned['id']}/messages",
                    headers=headers,
                    json=dict(
                        request_key=uuid4().hex,
                        expected_revision=owned["revision"],
                        body="متن",
                    ),
                )
                self.assertEqual(denied.status_code, 400)
                closed = await self.client.put(
                    f"/v1/admin/support/{owned['id']}/state",
                    headers=self.headers,
                    json=dict(
                        status="closed",
                        expected_revision=owned["revision"],
                        reason="رفع ظرفیت",
                    ),
                )
                self.assertEqual(closed.status_code, 200)
            async with self.connection.uow() as unit:
                count = await unit.execute(
                    text(
                        "SELECT COUNT(*) FROM tbl_support_messages "
                        "WHERE ticket_id=:id"
                    ),
                    {"id": ticket["id"]},
                )
                self.assertEqual(count.scalar_one(), 2)
        finally:
            await client.aclose()

    async def test_prior_role_sessions_and_preferences_survive_support_upgrade(
        self,
    ):
        assert self.settings.db is not None
        role = await self.post(
            "/v1/admin/roles",
            dict(
                code="prior_" + self.suffix,
                title="نقش قبلی",
                scopes=["customers:read"],
                is_active=True,
                reason="ثبت نقش",
            ),
        )
        prefs = (await self.get("/v1/admin/settings"))["data"]
        prefs["values"].pop("support")
        written = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json=dict(
                expected_revision=prefs["revision"], values=prefs["values"]
            ),
        )
        self.assertEqual(written.status_code, 200)
        legacy_revision = written.json()["data"]["revision"]
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    update(PreferencesRevisionTable)
                    .where(
                        PreferencesRevisionTable.revision == legacy_revision
                    )
                    .values(values_json=json.dumps(prefs["values"]))
                )
        migration = Config("alembic.ini")
        migration.set_main_option(
            "sqlalchemy.url",
            make_url(str(self.settings.db.dsn)).render_as_string(
                hide_password=False
            ),
        )
        with patch.dict(os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(
                command.downgrade, migration, "0027_staff_roles"
            )
            await asyncio.to_thread(command.upgrade, migration, "head")
        self.assertEqual(
            (await self.client.get("/v1/admin/auth/me")).status_code, 200
        )
        self.assertEqual(
            (await self.get(f"/v1/admin/roles/{role['id']}"))["data"][
                "scopes"
            ],
            ["customers:read"],
        )
        self.assertEqual((await self.get("/v1/admin/support"))["data"], [])
        availability = (await self.get("/v1/admin/support/policy"))["data"]
        self.assertTrue(availability["new_tickets_enabled"])

    async def test_support_bot_link_owned_exchange_and_disabled_fallback(self):
        from urllib.parse import parse_qs, urlsplit

        identity = {
            "telegram_id": int(uuid4().hex[:12], 16),
            "display_name": "ورود پشتیبانی",
        }
        path = "/v1/bot/support-link"
        self.assertEqual(
            (await self.client.post(path, json=identity)).status_code, 401
        )
        key = {"X-Papilio-Bot-Key": self.settings.security.bot_service_key}
        response = await self.client.post(path, headers=key, json=identity)
        self.assertEqual(response.status_code, 200)
        access = response.json()["data"]
        self.assertEqual(access["status"], "portal")
        parts = urlsplit(access["url"])
        self.assertEqual(parse_qs(parts.query), {"section": ["support"]})
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url=self.settings.public.customer_portal_origin,
        )
        try:
            exchanged = await client.post(
                "/v1/customer/auth/exchange",
                headers={
                    "Origin": self.settings.public.customer_portal_origin
                },
                json={"token": parts.fragment},
            )
            self.assertEqual(exchanged.status_code, 200)
            self.assertEqual(
                (await client.get("/v1/customer/support")).status_code, 200
            )
            replay = await client.post(
                "/v1/customer/auth/exchange",
                headers={
                    "Origin": self.settings.public.customer_portal_origin
                },
                json={"token": parts.fragment},
            )
            self.assertEqual(replay.status_code, 401)
            prefs = (await self.get("/v1/admin/settings"))["data"]
            prefs["values"]["support_handle"] = "@support_fixture"
            self.assertEqual(
                (
                    await self.client.put(
                        "/v1/admin/settings",
                        headers=self.headers,
                        json={
                            "expected_revision": prefs["revision"],
                            "values": prefs["values"],
                        },
                    )
                ).status_code,
                200,
            )
            with patch.object(self.settings.customer_auth, "enabled", False):
                fallback = await self.client.post(
                    path, headers=key, json=identity
                )
                self.assertEqual(fallback.status_code, 200)
                self.assertEqual(fallback.json()["data"]["status"], "contact")
                self.assertIsNone(fallback.json()["data"]["url"])
                self.assertEqual(
                    fallback.json()["data"]["support_handle"],
                    "@support_fixture",
                )
                prefs = (await self.get("/v1/admin/settings"))["data"]
                prefs["values"]["support_handle"] = None
                self.assertEqual(
                    (
                        await self.client.put(
                            "/v1/admin/settings",
                            headers=self.headers,
                            json={
                                "expected_revision": prefs["revision"],
                                "values": prefs["values"],
                            },
                        )
                    ).status_code,
                    200,
                )
                unavailable = await self.client.post(
                    path, headers=key, json=identity
                )
                self.assertEqual(
                    unavailable.json()["data"]["status"], "unavailable"
                )
                self.assertIsNone(unavailable.json()["data"]["url"])
        finally:
            await client.aclose()
