"""Native canonical product-term digest compatibility, not a bug baseline."""

import asyncio
import hashlib
import json

import httpx
from papilio.api.application import create_app

from src.config.providers import infrastructure_providers
from src.config.settings import PapilioSettings
from src.modules.sales.checkout.interfaces import ICheckoutOfferQuery
from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowFixture,
)


class CheckoutFingerprintWorkflowTest(StaffAdministrationWorkflowFixture):
    async def enable_offers(self):
        self.raw["purchase_intents"] = {
            "policy": {
                "enabled": True,
                "admission_mode": "allow_manual_profiles",
                "default_expiry_seconds": 3600,
            },
            "scan_cron": "* * * * *",
            "recheck_seconds": 1,
        }
        await self.client.aclose()
        await self.app.state.dishka_container.close()
        self.settings = PapilioSettings.model_validate(self.raw)
        self.app = create_app(
            self.settings,
            providers=infrastructure_providers(self.settings),
            middleware=(),
            docs_url=None,
        )
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="https://admin.example.com",
        )
        response = await self.client.post(
            "/v1/admin/auth/login",
            headers={"Origin": self.settings.public.admin_origin},
            json={"username": self.username, "password": self.password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.headers = {
            "Origin": self.settings.public.admin_origin,
            "X-CSRF-Token": response.json()["csrf_token"],
        }

    async def test_native_canonical_fallback_policy_digest(self):
        await self.exercise_canonical_digest(override=False)

    async def test_native_canonical_plan_override_policy_digest(self):
        await self.exercise_canonical_digest(override=True)

    async def exercise_canonical_digest(self, *, override):
        await self.enable_offers()
        preferences = (await self.get("/v1/admin/settings"))["data"]
        values = preferences["values"]
        fulfillment = self.settings.fulfillment.policy.model_dump(mode="json")
        fulfillment.update(renewal_trigger="quota", max_attempts=7)
        quota = self.settings.usage.policy.model_dump(mode="json")
        quota.update(grant_bytes=1234567, grant_seconds=47)
        ip_limit = dict(values["ip_defaults"])
        ip_limit.update(max_ips=3, mode="replace_oldest")
        values.update(
            fulfillment=fulfillment, quota_policy=quota, ip_defaults=ip_limit
        )
        saved = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": preferences["revision"],
                "values": values,
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        customer = await self.post(
            "/v1/admin/customers", {"display_name": "Canonical buyer"}
        )
        policies = {
            "fulfillment": fulfillment,
            "quota": quota,
            "ip_limit": ip_limit,
        }
        plan_data = {
            "code": "canonical_" + self.suffix,
            "title": "Canonical product",
            "quota_bytes": 987654321,
            "duration_days": 19,
            "price_rial": 120005,
        }
        if override:
            policies = {
                "fulfillment": {**fulfillment, "max_attempts": 11},
                "quota": {**quota, "grant_bytes": 2345678},
                "ip_limit": {**ip_limit, "max_ips": 5},
            }
            plan_data.update(
                fulfillment=policies["fulfillment"],
                quota_policy=policies["quota"],
                ip_limit=policies["ip_limit"],
            )
        plan = await self.post("/v1/admin/plans", plan_data)
        activated = await self.client.patch(
            f"/v1/admin/plans/{plan['id']}/active",
            headers=self.headers,
            json={"is_active": True},
        )
        self.assertEqual(activated.status_code, 200, activated.text)
        async with self.app.state.dishka_container() as scope:
            query = await scope.get(ICheckoutOfferQuery)
            offer = await query.get(customer["id"], plan["id"])
        expected_payload = {
            "plan_id": plan["id"],
            "group_id": None,
            "quota_bytes": 987654321,
            "duration_days": 19,
            "price_rial": 120005,
            "effective_policies": policies,
            "configurations": [],
        }
        expected_digest = await asyncio.to_thread(
            lambda: hashlib.sha256(
                json.dumps(
                    expected_payload, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
        )
        self.assertEqual(offer.offer_sha256, expected_digest)
        self.assertEqual(offer.price_rial, 120005)
        self.assertEqual(offer.delivery_mode, "manual_profiles")
