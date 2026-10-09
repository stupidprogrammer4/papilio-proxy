import asyncio
import json
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
from papilio.infra.db.transaction import transaction
from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import select
from starlette.middleware import Middleware

from src.config.middleware import SecurityHeadersMiddleware
from src.config.providers import infrastructure_providers
from src.config.settings import PapilioSettings
from src.modules.accounts.staff.app.passwords import Passwords
from src.modules.accounts.staff.app.services import StaffAuth
from src.modules.accounts.staff.domain.models import StaffModel
from src.modules.accounts.staff.infra.mysql import StaffRepository
from src.modules.accounts.staff.infra.readers import StaffSessionReader
from src.modules.network.configurations.infra.tables import (
    ConfigurationTable,
    ProfileTable,
)
from src.modules.sales.subscriptions.infra.tables import SubscriptionTable

TEST_URL = os.getenv("PAPILIO_TEST_DATABASE_URL")


@skipUnless(TEST_URL, "Requires isolated MySQL")
class ConfigurationWorkflowTest(IsolatedAsyncioTestCase):
    async def test_paid_profiles_export_secrets_retries_and_stable_links(
        self,
    ) -> None:
        migration = Config("alembic.ini")
        migration.set_main_option("sqlalchemy.url", str(TEST_URL))
        with patch.dict(os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(command.upgrade, migration, "head")
        raw = yaml.safe_load(Path("config.yml.sample").read_text())
        raw["db"]["dsn"] = TEST_URL
        raw["rate_limit"]["enabled"] = False
        raw["public"]["additional_admin_origins"] = ["http://localhost:4417"]
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
        suffix = uuid4().hex
        username = "config_" + suffix[:12]
        password = "local-test-password-123"
        try:
            async with connection.uow() as unit:
                await StaffAuth(
                    StaffRepository(unit),
                    Passwords(settings),
                    settings,
                    StaffSessionReader(unit),
                ).create_owner(username, password)
            async with connection.uow() as unit:
                async with transaction():
                    repo = StaffRepository(unit)
                    hashed = await Passwords(settings).hash(password)
                    reader_staff = await repo.create(
                        StaffModel(
                            username="reader_" + suffix[:12],
                            password_hash=hashed,
                            is_active=True,
                        )
                    )
                    await repo.add_grant(reader_staff.id, "network:read")
            app = create_app(
                settings,
                providers=infrastructure_providers(settings),
                middleware=[Middleware(SecurityHeadersMiddleware)],
                docs_url=None,
            )
            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="https://admin.example.com",
                ) as client:
                    short = await client.post(
                        "/v1/admin/auth/login",
                        headers={"Origin": settings.public.admin_origin},
                        json={"username": username, "password": "short"},
                    )
                    self.assertEqual(short.status_code, 422)
                    denied = await client.post(
                        "/v1/admin/auth/login",
                        headers={"Origin": "https://untrusted.example"},
                        json={"username": username, "password": password},
                    )
                    self.assertEqual(denied.status_code, 403)
                    login = await client.post(
                        "/v1/admin/auth/login",
                        headers={"Origin": "http://localhost:4417"},
                        json={"username": username, "password": password},
                    )
                    self.assertEqual(login.status_code, 200)
                    headers = {
                        "Origin": "http://localhost:4417",
                        "X-CSRF-Token": login.json()["csrf_token"],
                    }

                    async def post(
                        path: str, body: dict | None = None
                    ) -> dict:
                        response = await client.post(
                            path, headers=headers, json=body
                        )
                        self.assertEqual(
                            response.status_code, 200, response.text
                        )
                        return response.json()["data"]

                    customer = await post(
                        "/v1/admin/customers",
                        {"display_name": "آزمایش کانفیگ", "telegram_id": None},
                    )
                    plan = await post(
                        "/v1/admin/plans",
                        {
                            "code": "cfg_" + suffix[:12],
                            "title": "پلن کانفیگ",
                            "quota_bytes": 1_000_000_000,
                            "duration_days": 30,
                            "price_rial": 100_000,
                        },
                    )
                    activated = await client.patch(
                        f"/v1/admin/plans/{plan['id']}/active",
                        headers=headers,
                        json={"is_active": True},
                    )
                    self.assertEqual(activated.status_code, 200)
                    topup = await post(
                        "/v1/admin/payments/topups",
                        {
                            "customer_id": customer["id"],
                            "amount_rial": 100_000,
                        },
                    )
                    await post(
                        f"/v1/admin/payments/topups/{topup['id']}/approve",
                        {"bank_reference": "cfg_" + suffix},
                    )
                    purchase = await post(
                        "/v1/admin/subscriptions",
                        {
                            "customer_id": customer["id"],
                            "plan_id": plan["id"],
                            "purchase_key": "cfg_" + suffix,
                            "auto_renew": True,
                        },
                    )
                    subscription_id = purchase["id"]
                    protocols = [
                        "vless_reality",
                        "vless_tls",
                        "vmess_tls",
                        "trojan_tls",
                        "shadowsocks",
                        "hysteria2",
                        "wireguard",
                    ]
                    nodes = await asyncio.gather(
                        *(
                            post(
                                "/v1/admin/network/nodes",
                                {
                                    "code": f"cfg_{index}_{suffix[:12]}",
                                    "label": "نود آزمایش",
                                    "public_host": "vpn.example.com",
                                    "public_port": 443,
                                    "protocol": protocol,
                                },
                            )
                            for index, protocol in enumerate(protocols)
                        )
                    )
                    options = [
                        {
                            "protocol": "vless_reality",
                            "listen_address": "0.0.0.0",
                            "server_name": "www.example.com",
                            "target_port": 443,
                        },
                        *[
                            {
                                "protocol": protocol,
                                "listen_address": "0.0.0.0",
                                "server_name": "vpn.example.com",
                                "certificate_path": "/etc/cert.pem",
                                "private_key_path": "/etc/key.pem",
                                "transport": "tcp",
                            }
                            for protocol in protocols[1:4]
                        ],
                        {
                            "protocol": "shadowsocks",
                            "listen_address": "0.0.0.0",
                        },
                        {
                            "protocol": "hysteria2",
                            "listen_address": "0.0.0.0",
                            "server_name": "vpn.example.com",
                            "certificate_path": "/etc/cert.pem",
                            "private_key_path": "/etc/key.pem",
                        },
                        {
                            "protocol": "wireguard",
                            "listen_address": "0.0.0.0",
                            "server_address": "10.33.0.1/24",
                            "client_subnet": "10.33.0.0/24",
                            "allowed_ips": ["0.0.0.0/0"],
                            "dns": ["1.1.1.1"],
                        },
                    ]
                    configs = await asyncio.gather(
                        *(
                            post(
                                "/v1/admin/network/configurations",
                                {
                                    "node_id": registered["node"]["id"],
                                    "label": protocol,
                                    "options": option,
                                },
                            )
                            for registered, protocol, option in zip(
                                nodes, protocols, options, strict=True
                            )
                        )
                    )
                    ids = [configuration["id"] for configuration in configs]
                    assigned = await asyncio.gather(
                        *(
                            post(
                                f"/v1/admin/network/configurations/{id}/profiles",
                                {
                                    "subscription_id": subscription_id,
                                    "client_address": "10.33.0.2/32"
                                    if protocol == "wireguard"
                                    else None,
                                },
                            )
                            for id, protocol in zip(
                                ids, protocols, strict=True
                            )
                        )
                    )
                    profile_ids = [profile["id"] for profile in assigned]
                    retry = await post(
                        f"/v1/admin/network/configurations/{ids[0]}/profiles",
                        {"subscription_id": subscription_id},
                    )
                    self.assertEqual(retry["id"], profile_ids[0])
                    server_response = await client.post(
                        f"/v1/admin/network/configurations/{ids[0]}/server-download",
                        headers=headers,
                    )
                    self.assertEqual(server_response.status_code, 200)
                    self.assertEqual(
                        server_response.headers["cache-control"], "no-store"
                    )
                    content = json.loads(
                        server_response.json()["data"]["content"]
                    )
                    identity = content["inbounds"][0]["settings"]["clients"][
                        0
                    ]["id"]
                    private_key = content["inbounds"][0]["streamSettings"][
                        "realitySettings"
                    ]["privateKey"]
                    exported = await asyncio.gather(
                        *(
                            post(
                                f"/v1/admin/network/configurations/profiles/{id}/client-download"
                            )
                            for id in profile_ids
                        )
                    )
                    self.assertIn(identity, exported[0]["content"])
                    self.assertNotIn(private_key, exported[0]["content"])
                    self.assertIn(
                        "Address = 10.33.0.2/32", exported[-1]["content"]
                    )
                    changed_options = {
                        **options[0],
                        "server_name": "new.example.com",
                    }
                    updated = await client.put(
                        f"/v1/admin/network/configurations/{ids[0]}",
                        headers=headers,
                        json={
                            "label": "عنوان تازه",
                            "options": changed_options,
                        },
                    )
                    self.assertEqual(updated.status_code, 200)
                    refreshed_export = await post(
                        f"/v1/admin/network/configurations/profiles/{profile_ids[0]}/client-download"
                    )
                    self.assertIn(identity, refreshed_export["content"])
                    self.assertIn(
                        "sni=new.example.com", refreshed_export["content"]
                    )
                    metadata = await client.get(
                        "/v1/admin/network/configurations"
                    )
                    self.assertNotIn(private_key, metadata.text)
                    self.assertNotIn("encrypted_settings", metadata.text)
                    url = await post(
                        f"/v1/admin/network/configurations/subscriptions/{subscription_id}/link"
                    )
                    repeated = await post(
                        f"/v1/admin/network/configurations/subscriptions/{subscription_id}/link"
                    )
                    self.assertEqual(url, repeated)
                    token = url["url"].rsplit("/", 1)[-1]
                    unavailable = await client.get(f"/s/{token}")
                    self.assertEqual(unavailable.status_code, 404)
                    rotated = await post(
                        f"/v1/admin/network/configurations/subscriptions/{subscription_id}/rotate-link"
                    )
                    self.assertNotEqual(rotated, url)
                    old_url = await client.get(f"/s/{token}")
                    self.assertEqual(old_url.status_code, 404)
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="https://admin.example.com",
                ) as reader_client:
                    reader_login = await reader_client.post(
                        "/v1/admin/auth/login",
                        headers={"Origin": settings.public.admin_origin},
                        json={
                            "username": reader_staff.username,
                            "password": password,
                        },
                    )
                    self.assertEqual(reader_login.status_code, 200)
                    reader_headers = {
                        "Origin": settings.public.admin_origin,
                        "X-CSRF-Token": reader_login.json()["csrf_token"],
                    }
                    listed = await reader_client.get(
                        "/v1/admin/network/configurations"
                    )
                    self.assertEqual(listed.status_code, 200)
                    denied_secret = await reader_client.post(
                        f"/v1/admin/network/configurations/{ids[0]}/server-download",
                        headers=reader_headers,
                    )
                    self.assertEqual(denied_secret.status_code, 403)
                async with connection.uow() as independent:
                    saved = await independent.execute(
                        select(ConfigurationTable).where(
                            ConfigurationTable.id == ids[0]
                        )
                    )
                    self.assertNotIn(
                        private_key, saved.scalar_one().encrypted_settings
                    )
                    saved_profile = await independent.execute(
                        select(ProfileTable).where(
                            ProfileTable.id == profile_ids[0]
                        )
                    )
                    self.assertNotIn(
                        identity,
                        saved_profile.scalar_one().encrypted_credentials,
                    )
                    saved_subscription = await independent.execute(
                        select(SubscriptionTable).where(
                            SubscriptionTable.id == subscription_id
                        )
                    )
                    self.assertEqual(
                        saved_subscription.scalar_one().status,
                        "pending_provision",
                    )
            finally:
                await app.state.dishka_container.close()
        finally:
            await connection.dispose()
