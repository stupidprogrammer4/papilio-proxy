import asyncio
import base64
import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pymysql
from alembic import command
from alembic.config import Config
from papilio.api.application import create_app
from papilio.security.crypto import encrypt, hash_sha256
from sqlalchemy.engine import make_url

from src.config.providers import infrastructure_providers
from src.config.settings import PapilioSettings
from src.modules.network.configurations.app.exports import (
    ConfigurationCredentials,
)
from src.modules.network.configurations.domain.dtos import (
    RealityOptions,
    ShadowsocksOptions,
)
from src.modules.network.provisioning.domain.results import ProvisionPayload
from tests.test_automation_workflow import TEST_URL, AutomationWorkflowFixture


class FoundationsMigrationTest(AutomationWorkflowFixture):
    async def test_upgrade_preserves_old_profiles_credentials_links_and_feed(
        self,
    ):
        database = "papilio_upgrade_test_" + uuid4().hex[:12]
        url = make_url(str(TEST_URL)).set(database=database)
        assert url.host == "127.0.0.1" and "test" in database
        assert url.username and url.password
        token = secrets.token_urlsafe(32)
        credentials = ConfigurationCredentials()
        options = RealityOptions(
            protocol="vless_reality",
            listen_address="0.0.0.0",
            server_name="example.com",
            target_port=443,
        )
        stored = credentials.settings(options)
        shadow = credentials.settings(
            ShadowsocksOptions(
                protocol="shadowsocks", listen_address="0.0.0.0"
            )
        )
        encrypted_shadow = encrypt(
            shadow.model_dump_json(),
            self.settings.configuration_encryption_key,
        )
        client = credentials.client(options)
        encrypted_settings = encrypt(
            stored.model_dump_json(),
            self.settings.configuration_encryption_key,
        )
        encrypted_client = encrypt(
            client.model_dump_json(),
            self.settings.configuration_encryption_key,
        )
        encrypted_payload = encrypt(
            ProvisionPayload(
                core_id=1,
                listen_port=7443,
                settings=stored,
                credentials=client,
                client_address=None,
            ).model_dump_json(),
            self.settings.configuration_encryption_key,
        )
        encrypted_token = encrypt(
            token, self.settings.configuration_encryption_key
        )

        def connect(selected=None):
            assert url.username is not None and url.password is not None
            assert url.host is not None
            return pymysql.connect(
                host=url.host,
                port=url.port or 3306,
                user=url.username,
                password=url.password,
                database=selected,
                autocommit=True,
            )

        def prepare():
            connection = connect()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("CREATE DATABASE " + database)
            finally:
                connection.close()
            migration = Config("alembic.ini")
            migration.set_main_option(
                "sqlalchemy.url", url.render_as_string(hide_password=False)
            )
            command.upgrade(migration, "0013_subscription_ip_limits")
            connection = connect(database)
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO tbl_customers (id, display_name, "
                        "is_active) "
                        "VALUES (1, 'old customer', 1)"
                    )
                    cursor.execute(
                        "INSERT INTO tbl_plans (id, code, title, quota_bytes, "
                        "duration_days, price_rial, sort_order, "
                        "is_active) VALUES "
                        "(1, 'old', 'old plan', 1000000, 30, 100000, 0, 1)"
                    )
                    cursor.execute(
                        "INSERT INTO tbl_nodes (id, code, label, public_host, "
                        "public_port, protocol, agent_key_hash, "
                        "is_enabled) VALUES "
                        "(1, 'old', 'old node', 'old.example.invalid', 7443, "
                        "'vless_reality', %s, 1)",
                        (hash_sha256("fixture-node-key"),),
                    )
                    cursor.execute(
                        "INSERT INTO tbl_subscriptions (id, purchase_key, "
                        "customer_id, plan_id, quota_bytes, price_rial, "
                        "duration_days, expires_at, status, auto_renew, "
                        "renewal_count) VALUES (1, 'old-order', 1, 1, "
                        "1000000, "
                        "100000, 30, %s, 'active', 0, 0)",
                        (
                            datetime.now(UTC).replace(tzinfo=None)
                            + timedelta(days=1),
                        ),
                    )
                    cursor.execute(
                        "INSERT INTO tbl_configurations (id, node_id, label, "
                        "protocol, encrypted_settings) VALUES (1, 1, 'old "
                        "inbound', 'vless_reality', %s)",
                        (encrypted_settings,),
                    )
                    cursor.execute(
                        "INSERT INTO tbl_profiles (id, configuration_id, "
                        "subscription_id, encrypted_credentials) VALUES "
                        "(1, 1, 1, "
                        "%s)",
                        (encrypted_client,),
                    )
                    cursor.execute(
                        "INSERT INTO tbl_subscription_links (id, "
                        "subscription_id, "
                        "token_hash, encrypted_token) VALUES (1, 1, %s, %s)",
                        (hash_sha256(token), encrypted_token),
                    )
            finally:
                connection.close()
            connection = connect(database)
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO tbl_nodes "
                        "(id, code, label, public_host, "
                        "public_port, protocol, "
                        "agent_key_hash, is_enabled) VALUES "
                        "(2, 'old-ss', 'old ss', 'ss.example.invalid', 8443, "
                        "'shadowsocks', %s, 1)",
                        (hash_sha256("fixture-ss-key"),),
                    )
                    cursor.execute(
                        "INSERT INTO tbl_configurations "
                        "(id, node_id, label, protocol, encrypted_settings) "
                        "VALUES (2, 2, 'old ss', 'shadowsocks', %s)",
                        (encrypted_shadow,),
                    )
            finally:
                connection.close()
            command.upgrade(migration, "0017_inbound_revisions")
            prior_policy = {
                key: value
                for key, value in self.raw["fulfillment"]["policy"].items()
                if key != "renewal_trigger"
            }
            connection = connect(database)
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE tbl_subscriptions SET used_bytes=150000, "
                        "fulfillment_json=%s WHERE id=1",
                        (json.dumps(prior_policy),),
                    )
                    cursor.execute(
                        "INSERT INTO tbl_provision_requests (id, "
                        "subscription_id, generation, policy_json, state, "
                        "deadline_at) VALUES (1, 1, 0, %s, 'attention', %s)",
                        (
                            json.dumps(prior_policy),
                            datetime.now(UTC).replace(tzinfo=None)
                            + timedelta(days=1),
                        ),
                    )
                    cursor.execute(
                        "INSERT INTO tbl_provision_tasks (id, request_id, "
                        "configuration_id, configuration_revision, "
                        "profile_id, node_id, encrypted_payload, action, "
                        "state, attempts, available_at) VALUES (1, 1, 1, 1, "
                        "1, 1, %s, 'apply', 'failed', 2, %s)",
                        (
                            encrypted_payload,
                            datetime.now(UTC).replace(tzinfo=None),
                        ),
                    )
            finally:
                connection.close()
            command.upgrade(migration, "head")

        def persisted():
            connection = connect(database)
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT c.encrypted_settings, "
                        "p.encrypted_credentials, "
                        "l.encrypted_token, c.listen_port, "
                        "c.port_network, k.kind "
                        "FROM tbl_configurations c JOIN tbl_profiles p ON "
                        "p.configuration_id=c.id JOIN "
                        "tbl_subscription_links l ON "
                        "l.subscription_id=p.subscription_id JOIN "
                        "tbl_cores k ON "
                        "k.id=c.core_id WHERE c.id=1"
                    )
                    primary = cursor.fetchone()
                    cursor.execute(
                        "SELECT c.port_network, c.encrypted_settings, "
                        "p.network FROM tbl_configurations c "
                        "JOIN tbl_inbound_ports p ON p.configuration_id=c.id "
                        "WHERE c.id=2 ORDER BY p.network"
                    )
                    secondary = cursor.fetchall()
                    cursor.execute(
                        "SELECT s.used_bytes, s.base_quota_bytes, "
                        "s.quota_policy_json, s.fulfillment_json, r.state, "
                        "r.completion, r.policy_json, t.state, t.attempts, "
                        "t.encrypted_payload FROM tbl_subscriptions s JOIN "
                        "tbl_provision_requests r ON r.subscription_id=s.id "
                        "JOIN tbl_provision_tasks t ON t.request_id=r.id "
                        "WHERE s.id=1"
                    )
                    lifecycle = cursor.fetchone()
                    assert lifecycle is not None
                    return primary, secondary, lifecycle
            finally:
                connection.close()

        def drop():
            connection = connect()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("DROP DATABASE IF EXISTS " + database)
            finally:
                connection.close()

        app = None
        try:
            await asyncio.to_thread(prepare)
            found, secondary, lifecycle = await asyncio.to_thread(persisted)
            self.assertEqual(lifecycle[:3], (150000, 1000000, None))
            self.assertEqual(
                json.loads(lifecycle[3])["renewal_trigger"], "expiry"
            )
            self.assertEqual(lifecycle[4:6], ("attention", "refund"))
            self.assertEqual(
                json.loads(lifecycle[6])["renewal_trigger"], "expiry"
            )
            self.assertEqual(lifecycle[7:], ("failed", 2, encrypted_payload))
            self.assertEqual(
                secondary,
                (
                    ("dual", encrypted_shadow, "tcp"),
                    ("dual", encrypted_shadow, "udp"),
                ),
            )
            self.assertEqual(
                found,
                (
                    encrypted_settings,
                    encrypted_client,
                    encrypted_token,
                    7443,
                    "tcp",
                    "xray",
                ),
            )
            raw = {
                **self.raw,
                "db": {
                    **self.raw["db"],
                    "dsn": url.render_as_string(hide_password=False),
                },
            }
            settings = PapilioSettings.model_validate(raw)
            app = create_app(
                settings,
                providers=infrastructure_providers(settings),
                middleware=(),
                docs_url=None,
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://admin.example.com",
            ) as consumer:
                response = await consumer.get("/s/" + token)
            self.assertEqual(response.status_code, 200)
            feed = base64.b64decode(response.text).decode()
            self.assertIn("@old.example.invalid:7443", feed)
            self.assertIn(client.identity, feed)
        finally:
            if app is not None:
                await app.state.dishka_container.close()
            await asyncio.to_thread(drop)
