import asyncio
import os
from datetime import UTC, datetime
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

TEST_URL = os.getenv("PAPILIO_TEST_DATABASE_URL")


@skipUnless(TEST_URL, "Requires an isolated PAPILIO_TEST_DATABASE_URL")
class NodeQualityWorkflowTest(IsolatedAsyncioTestCase):
    async def test_registered_node_probe_and_ranked_quality(self) -> None:
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", str(TEST_URL))
        with patch.dict(os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(command.upgrade, config, "head")
        with open("config.yml.sample", encoding="utf-8") as source:
            raw = yaml.safe_load(source)
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
        code = "node_" + uuid4().hex[:12]
        try:
            async with connection.uow() as unit:
                await StaffAuth(
                    StaffRepository(unit),
                    Passwords(settings),
                    settings,
                    StaffSessionReader(unit),
                ).create_owner(username, "local-only-password-123")
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
                    login = await client.post(
                        "/v1/admin/auth/login",
                        headers={"Origin": settings.public.admin_origin},
                        json={
                            "username": username,
                            "password": "local-only-password-123",
                        },
                    )
                    self.assertEqual(login.status_code, 200)
                    headers = {
                        "Origin": settings.public.admin_origin,
                        "X-CSRF-Token": login.json()["csrf_token"],
                    }
                    created = await client.post(
                        "/v1/admin/network/nodes",
                        headers=headers,
                        json={
                            "code": code,
                            "label": "نود آزمایشی",
                            "public_host": "example.invalid",
                            "public_port": 443,
                            "protocol": "vless_reality",
                        },
                    )
                    self.assertEqual(created.status_code, 200)
                    node_id = created.json()["data"]["node"]["id"]
                    agent_key = created.json()["data"]["agent_key"]
                    listed = await client.get("/v1/admin/network/nodes")
                    self.assertEqual(listed.status_code, 200)
                    self.assertNotIn(agent_key, listed.text)
                    sample = {
                        "event_id": uuid4().hex,
                        "client_network": "local-test",
                        "success": True,
                        "latency_ms": 50,
                        "sampled_at": datetime.now(UTC).isoformat(),
                    }
                    denied = await client.post(
                        f"/v1/nodes/{code}/probes", json=sample
                    )
                    self.assertEqual(denied.status_code, 401)
                    probe_headers = {"X-Papilio-Node-Key": agent_key}
                    events = [
                        {
                            **sample,
                            "event_id": uuid4().hex,
                            "latency_ms": latency,
                        }
                        for latency in (50, 70, 90)
                    ]
                    responses = await asyncio.gather(
                        *(
                            client.post(
                                f"/v1/nodes/{code}/probes",
                                json=event,
                                headers=probe_headers,
                            )
                            for event in events
                        )
                    )
                    self.assertTrue(
                        all(
                            response.status_code == 200
                            for response in responses
                        )
                    )
                    replay = await client.post(
                        f"/v1/nodes/{code}/probes",
                        json=events[0],
                        headers=probe_headers,
                    )
                    self.assertEqual(replay.status_code, 200)
                    changed = await client.post(
                        f"/v1/nodes/{code}/probes",
                        json={**events[0], "latency_ms": 500},
                        headers=probe_headers,
                    )
                    self.assertEqual(changed.status_code, 409)
                    enabled = await client.patch(
                        f"/v1/admin/network/nodes/{node_id}/enabled",
                        headers=headers,
                        json={"enabled": True},
                    )
                    self.assertEqual(enabled.status_code, 200)
                    quality = await client.get(
                        "/v1/admin/network/quality?client_network=local-test"
                    )
                    self.assertEqual(quality.status_code, 200)
                    row = next(
                        item
                        for item in quality.json()["data"]
                        if item["node_id"] == node_id
                    )
                    self.assertEqual(row["sample_count"], 3)
                    self.assertEqual(row["average_latency_ms"], 70)
                    self.assertEqual(row["score"], 70.0)
            finally:
                await app.state.dishka_container.close()
        finally:
            await connection.dispose()
