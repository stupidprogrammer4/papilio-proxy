import asyncio
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select, update
from sqlmodel import col

from src.modules.accounts.customers.infra.tables import CustomerTable
from src.modules.sales.subscriptions.infra.tables import SubscriptionTable
from tests.test_fulfillment_workflow import FulfillmentWorkflowFixture


class CustomerAccessWorkflowTest(FulfillmentWorkflowFixture):
    async def asyncSetUp(self):
        from unittest.mock import patch
        from uuid import uuid4

        from papilio.infra.db.connection import DBConnection
        from papilio.infra.db.uow import MySQLUnitOfWork
        from sqlalchemy import text
        from sqlalchemy.engine import make_url

        from tests.test_automation_workflow import TEST_URL

        self.schema = (
            "papilio_upgrade_test_customer_access_" + uuid4().hex[:12]
        )
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
        from sqlalchemy import text

        await super().asyncTearDown()
        async with self.maintenance.uow() as unit:
            await unit.execute(text(f"DROP DATABASE `{self.schema}`"))
        await self.maintenance.dispose()

    async def activated(self):
        subscription, request, nodes, _ = await self.setup_sale()
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        tasks = (
            await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
        )["data"]
        claims = await asyncio.gather(
            *(self.claim(task, nodes) for task in tasks)
        )
        await asyncio.gather(
            *(
                self.ack(task, *claim)
                for task, claim in zip(tasks, claims, strict=True)
            )
        )
        subscription = (
            await self.get(f"/v1/admin/subscriptions/{subscription['id']}")
        )["data"]
        return subscription, request, tasks, nodes

    async def change_access(
        self,
        customer_id,
        *,
        account=True,
        services=True,
        renewals=True,
        clock=None,
    ):
        customer = (await self.get(f"/v1/admin/customers/{customer_id}"))[
            "data"
        ]
        body = {
            "request_key": "access_"
            + self.suffix
            + "_"
            + str(asyncio.get_running_loop().time()),
            "expected": {
                k: customer[k]
                for k in ("is_active", "services_enabled", "renewals_enabled")
            },
            "values": {
                "is_active": account,
                "services_enabled": services,
                "renewals_enabled": renewals,
            },
            "reason": "تغییر دسترسی آزمون",
            "clock": clock,
        }
        result = await self.client.put(
            f"/v1/admin/customers/{customer_id}/access",
            headers=self.headers,
            json=body,
        )
        self.assertEqual(result.status_code, 200)
        return result.json()["data"], body

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

    async def check_hold(self, subscription_id):
        from src.modules.sales.subscriptions.interfaces import (
            ICustomerHoldCommand,
        )

        async with self.app.state.dishka_container() as scope:
            command = await scope.get(ICustomerHoldCommand)
            result = await command.check(subscription_id)
            return result.status

    async def finalize(self, customer_id):
        from src.modules.sales.subscriptions.interfaces import (
            ICustomerHoldFinalizeCommand,
        )

        async with self.app.state.dishka_container() as scope:
            command = await scope.get(ICustomerHoldFinalizeCommand)
            result = await command.check(customer_id)
            return result

    async def test_account_disable_preserves_paid_delivery_and_revokes_links(
        self,
    ):
        subscription, _, tasks, nodes = await self.activated()
        sid, cid = subscription["id"], subscription["customer_id"]
        customer = (await self.get(f"/v1/admin/customers/{cid}"))["data"]
        account, _, _ = await self.account(customer["telegram_id"])
        bot_headers = {
            "X-Papilio-Bot-Key": self.settings.security.bot_service_key
        }
        identity = {
            "telegram_id": customer["telegram_id"],
            "display_name": "تغییر نام",
        }
        before = await self.client.post(
            "/v1/bot/account-link", headers=bot_headers, json=identity
        )
        token = before.json()["data"]["url"].rsplit("#", 1)[-1]
        url = (
            await self.post(
                f"/v1/admin/network/configurations/subscriptions/{sid}/link"
            )
        )["url"]
        try:
            stopped, _ = await self.change_access(cid, account=False)
            self.assertFalse(stopped["is_active"])
            self.assertFalse(stopped["service_hold_pending"])
            self.assertEqual(
                (await account.get("/v1/customer/auth/me")).status_code, 401
            )
            unavailable = await self.client.post(
                "/v1/bot/account-link", headers=bot_headers, json=identity
            )
            self.assertEqual(unavailable.status_code, 401)
            self.assertEqual(
                (
                    await self.client.get("/s/" + url.rsplit("/", 1)[-1])
                ).status_code,
                200,
            )
            node = nodes[0]
            admission = await self.client.post(
                f"/v1/nodes/{node['node']['code']}/ip-admission",
                headers={"X-Papilio-Node-Key": node["agent_key"]},
                json={"subscription_id": sid, "source_ip": "198.51.100.21"},
            )
            self.assertEqual(admission.status_code, 200)
            self.assertTrue(admission.json()["data"]["allowed"])
            await self.change_access(cid)
            self.assertEqual(
                (await account.get("/v1/customer/auth/me")).status_code, 401
            )
            old = await account.post(
                "/v1/customer/auth/exchange",
                headers={
                    "Origin": self.settings.public.customer_portal_origin
                },
                json={"token": token},
            )
            self.assertEqual(old.status_code, 401)
            fresh, _, _ = await self.account(customer["telegram_id"])
            await fresh.aclose()
        finally:
            await account.aclose()

    async def test_fast_reenable_preserves_hold_final_usage_then_resume(
        self,
    ):
        subscription, _, tasks, nodes = await self.activated()
        sid, cid = subscription["id"], subscription["customer_id"]
        url = (
            await self.post(
                f"/v1/admin/network/configurations/subscriptions/{sid}/link"
            )
        )["url"]
        node = next(
            row for row in nodes if row["node"]["id"] == tasks[0]["node_id"]
        )
        node_headers = {"X-Papilio-Node-Key": node["agent_key"]}
        allocated = await self.client.post(
            f"/v1/nodes/{node['node']['code']}/usage/grants",
            headers=node_headers,
            json={
                "profile_id": tasks[0]["profile_id"],
                "generation": 0,
                "request_key": "before_" + self.suffix,
                "requested_bytes": 1000000,
            },
        )
        self.assertEqual(allocated.status_code, 200)
        grant = allocated.json()["data"]
        wallet = (await self.get(f"/v1/admin/payments/wallets/{cid}"))["data"]
        stopped, body = await self.change_access(
            cid, services=False, renewals=False, clock="pause"
        )
        self.assertTrue(stopped["service_hold_pending"])
        enabled, _ = await self.change_access(cid, renewals=False)
        self.assertTrue(enabled["service_hold_pending"])
        replay = await self.client.put(
            f"/v1/admin/customers/{cid}/access",
            headers=self.headers,
            json=body,
        )
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.json()["data"]["services_enabled"])
        self.assertEqual(
            (
                await self.client.get("/s/" + url.rsplit("/", 1)[-1])
            ).status_code,
            404,
        )
        status = await self.client.get(
            "/s/" + url.rsplit("/", 1)[-1] + "/status"
        )
        self.assertEqual(status.json()["data"]["status"], "customer_hold")
        self.assertFalse(await self.finalize(cid))
        self.assertEqual(await self.check_hold(sid), "revoking")
        new = await self.client.post(
            f"/v1/nodes/{node['node']['code']}/usage/grants",
            headers=node_headers,
            json={
                "profile_id": tasks[0]["profile_id"],
                "generation": 0,
                "request_key": "after_" + self.suffix,
                "requested_bytes": 1000000,
            },
        )
        self.assertEqual(new.status_code, 409)
        final = await self.client.post(
            f"/v1/nodes/{node['node']['code']}/usage/grants/{grant['id']}/reports",
            headers=node_headers,
            json={
                "event_id": "final_" + self.suffix,
                "sequence": 1,
                "upload_bytes": 15,
                "download_bytes": 25,
                "sampled_at": datetime.now(UTC).isoformat(),
                "final": True,
            },
        )
        self.assertEqual(final.status_code, 200)
        claims = await asyncio.gather(
            *(self.claim(task, nodes) for task in tasks)
        )
        await asyncio.gather(
            *(
                self.ack(task, *claim, outcome="revoked")
                for task, claim in zip(tasks, claims, strict=True)
            )
        )
        self.assertTrue(await self.finalize(cid))
        row = (await self.get(f"/v1/admin/subscriptions/{sid}"))["data"]
        self.assertEqual(row["status"], "suspended")
        self.assertEqual(row["used_bytes"], 40)
        self.assertEqual(
            (
                await self.client.get("/s/" + url.rsplit("/", 1)[-1])
            ).status_code,
            404,
        )
        resume = await self.client.put(
            f"/v1/admin/subscriptions/{sid}/resumption",
            headers=self.headers,
            json={
                "request_key": "resume_" + self.suffix,
                "reason": "ادامه پس از توقف مشتری",
            },
        )
        self.assertEqual(resume.status_code, 200)
        claims = await asyncio.gather(
            *(self.claim(task, nodes) for task in tasks)
        )
        await asyncio.gather(
            *(
                self.ack(task, *claim)
                for task, claim in zip(tasks, claims, strict=True)
            )
        )
        self.assertEqual(
            (
                await self.client.get("/s/" + url.rsplit("/", 1)[-1])
            ).status_code,
            200,
        )
        self.assertEqual(
            (await self.get(f"/v1/admin/payments/wallets/{cid}"))["data"],
            wallet,
        )
        history = await self.get(
            f"/v1/admin/customers/{cid}/access-history?per_page=1"
        )
        self.assertEqual(history["meta"]["pager"]["total_items"], 2)
        self.assertEqual(len(history["data"]), 1)
        async with self.connection.uow() as independent:
            stored = (
                await independent.execute(
                    select(CustomerTable).where(col(CustomerTable.id) == cid)
                )
            ).scalar_one()
            self.assertFalse(stored.service_hold_pending)

    async def test_renewal_pause_has_no_debit_and_unactivated_hold_recovers(
        self,
    ):
        subscription, request, nodes, _ = await self.setup_sale()
        sid, cid = subscription["id"], subscription["customer_id"]
        await self.change_access(
            cid, services=False, renewals=False, clock="continue"
        )
        self.assertEqual(await self.check_hold(sid), "suspended")
        self.assertTrue(await self.finalize(cid))
        await self.change_access(cid, renewals=False)
        resume = await self.client.put(
            f"/v1/admin/subscriptions/{sid}/resumption",
            headers=self.headers,
            json={
                "request_key": "resume_" + self.suffix,
                "reason": "ادامهٔ خرید راه‌اندازی نشده",
            },
        )
        self.assertEqual(resume.status_code, 200)
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        tasks = (
            await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
        )["data"]
        self.assertEqual(len(tasks), len(nodes))
        claims = await asyncio.gather(
            *(self.claim(task, nodes) for task in tasks)
        )
        await asyncio.gather(
            *(
                self.ack(task, *claim)
                for task, claim in zip(tasks, claims, strict=True)
            )
        )
        async with self.connection.uow() as unit:
            await unit.execute(
                update(SubscriptionTable)
                .where(col(SubscriptionTable.id) == sid)
                .values(
                    provisioning_managed=False,
                    expires_at=datetime.now(UTC).replace(tzinfo=None)
                    - timedelta(seconds=1),
                )
            )
            await unit.commit()
        from src.modules.sales.subscriptions.interfaces import (
            ISubscriptionCommand,
        )

        async with self.app.state.dishka_container() as scope:
            command = await scope.get(ISubscriptionCommand)
            row = await command.renew_due(sid)
            self.assertEqual(row.renewal_count, 0)
        await self.change_access(cid)
        async with self.app.state.dishka_container() as scope:
            command = await scope.get(ISubscriptionCommand)
            row = await command.renew_due(sid)
            self.assertEqual(row.renewal_count, 1)

    async def test_native_scheduler_queue_worker_processes_customer_hold(self):
        from tests.scheduler_runtime import exercise_native_customer_hold

        subscription, _, _, _ = await self.activated()
        await self.change_access(
            subscription["customer_id"],
            services=False,
            renewals=False,
            clock="pause",
        )
        schedule = (
            await self.get("/v1/admin/automation/schedules/customer_holds")
        )["data"]
        interval_policy = {
            "enabled": True,
            "mode": "interval",
            "interval_seconds": 15,
            "cron": None,
            "timezone": None,
            "batch_size": schedule["batch_size"],
            "recheck_seconds": None,
        }
        saved = await self.client.put(
            "/v1/admin/automation/schedules/customer_holds",
            headers=self.headers,
            json={
                "expected_revision": schedule["revision"],
                "values": interval_policy,
                "reason": "آزمون فاصلهٔ ثابت واقعی",
            },
        )
        self.assertEqual(saved.status_code, 200)
        result = await asyncio.to_thread(
            exercise_native_customer_hold, self.raw, subscription["id"]
        )
        self.assertEqual(result, ("revoking", "suspend"))

    async def test_creation_policy_is_versioned_and_admin_can_override(self):
        current = (await self.get("/v1/admin/settings"))["data"]
        choice = {
            "is_active": False,
            "services_enabled": False,
            "renewals_enabled": False,
        }
        current["values"]["customer_creation_access"] = choice
        response = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": current["revision"],
                "values": current["values"],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            (await self.get("/v1/admin/customers/creation-policy"))["data"],
            choice,
        )
        automatic = await self.post(
            "/v1/admin/customers", {"display_name": "پیش‌فرض غیرفعال"}
        )
        self.assertTrue(all(automatic[k] == v for k, v in choice.items()))
        override = {k: True for k in choice}
        explicit = await self.post(
            "/v1/admin/customers",
            {"display_name": "دسترسی اختصاصی", "access": override},
        )
        self.assertTrue(all(explicit[k] == v for k, v in override.items()))

        from src.modules.accounts.customers.interfaces import ICustomerService

        async with self.app.state.dishka_container() as scope:
            async with self.connection.uow():
                service = await scope.get(ICustomerService)
                row = await service.ensure_telegram(
                    990000 + int(self.suffix[:6], 16), "ربات"
                )
                self.assertFalse(row.is_active)
                self.assertFalse(row.services_enabled)
                self.assertFalse(row.renewals_enabled)

    async def test_pending_customer_scan_rotates_past_unfinished_revocations(
        self,
    ):
        from src.modules.accounts.customers.infra.mysql import (
            CustomerRepository,
        )
        from src.modules.sales.subscriptions.interfaces import (
            ICustomerHoldFinalizeCommand,
        )

        subscription, _, _, _ = await self.activated()
        held, _ = await self.change_access(
            subscription["customer_id"], services=False, clock="continue"
        )
        other = await self.post(
            "/v1/admin/customers", {"display_name": "توقف دوم"}
        )
        await self.change_access(other["id"], services=False, clock="continue")
        async with self.connection.uow() as unit:
            await unit.execute(
                update(CustomerTable)
                .where(col(CustomerTable.id) == held["id"])
                .values(
                    updated_at=datetime.now(UTC).replace(tzinfo=None)
                    - timedelta(minutes=2)
                )
            )
            await unit.execute(
                update(CustomerTable)
                .where(col(CustomerTable.id) == other["id"])
                .values(
                    updated_at=datetime.now(UTC).replace(tzinfo=None)
                    - timedelta(minutes=1)
                )
            )
            await unit.commit()
        async with self.connection.uow() as unit:
            ids = await CustomerRepository(unit).hold_pending_ids(True, 1)
            self.assertEqual(ids, [held["id"]])
        async with self.app.state.dishka_container() as scope:
            command = await scope.get(ICustomerHoldFinalizeCommand)
            self.assertFalse(await command.check(held["id"]))
        async with self.connection.uow() as unit:
            ids = await CustomerRepository(unit).hold_pending_ids(True, 1)
            self.assertEqual(ids, [other["id"]])
