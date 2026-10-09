import asyncio
import json
import secrets
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import httpx
import yaml
from papilio.api.application import create_app
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.uow import MySQLUnitOfWork
from PIL import Image
from sqlalchemy import text
from sqlalchemy.engine import make_url

from src.config.providers import infrastructure_providers
from src.config.settings import PapilioSettings
from src.modules.operations.backups.app.archives import RecoveryArchives
from src.modules.operations.backups.domain.contracts import RecoverySettings
from src.modules.operations.backups.infra.mysql import MySQLRecovery
from tests.test_trials_workflow import TrialsWorkflowTest


class RecoveryWorkflowTest(TrialsWorkflowTest):
    async def table_counts(self, connection):
        async with connection.uow() as unit:
            tables = (
                (
                    await unit.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema=DATABASE() ORDER BY table_name"
                        )
                    )
                )
                .scalars()
                .all()
            )
            query = " UNION ALL ".join(
                f"SELECT '{name}', COUNT(*) FROM `{name}`" for name in tables
            )
            result = (await unit.execute(text(query))).all()
        return [tuple(row) for row in result]

    async def test_populated_restore_auth_crypto_finance_and_safe_failures(
        self,
    ):
        assert self.settings.db is not None
        plan = await self.source()
        customer, headers, customer_id = await self.account()
        other, _, _ = await self.account()
        target_schema = "papilio_upgrade_test_restore_" + uuid4().hex[:12]
        target_url = make_url(self.settings.db.dsn).set(database=target_schema)
        target = DBConnection(
            dsn=target_url.render_as_string(hide_password=False),
            pool_size=2,
            max_overflow=0,
            pool_timeout=30,
            pool_recycle=1800,
            uow_factory=MySQLUnitOfWork,
        )
        restored_app = None
        try:
            trial_response = await customer.post(
                "/v1/customer/trials",
                headers=headers,
                json={"request_key": uuid4().hex},
            )
            self.assertEqual(trial_response.status_code, 200)
            trial = trial_response.json()["data"]
            topup = await self.post(
                "/v1/admin/payments/topups",
                {"customer_id": customer_id, "amount_rial": 300000},
            )

            def image():
                output = BytesIO()
                Image.new("RGB", (32, 32), "blue").save(output, "PNG")
                return output.getvalue()

            receipt_path = f"/v1/customer/topups/{topup['id']}/receipts"
            uploaded = await customer.post(
                receipt_path,
                headers=headers,
                files={
                    "file": ("receipt.png", await asyncio.to_thread(image))
                },
            )
            self.assertEqual(uploaded.status_code, 200)
            receipt_id = uploaded.json()["data"]["id"]
            receipt_before = await customer.get(f"{receipt_path}/{receipt_id}")
            reference = "restore_" + self.suffix
            await self.post(
                f"/v1/admin/payments/topups/{topup['id']}/approve",
                {"bank_reference": reference},
            )
            purchase_data = {
                "customer_id": customer_id,
                "plan_id": plan["id"],
                "purchase_key": "restore_" + uuid4().hex,
            }
            paid = await self.post("/v1/admin/subscriptions", purchase_data)
            ticket = await customer.post(
                "/v1/customer/support",
                headers=headers,
                json={
                    "request_key": uuid4().hex,
                    "subject": "بازیابی",
                    "body": "متن خصوصی پس از بازیابی",
                },
            )
            self.assertEqual(ticket.status_code, 200)
            policy_before = (await self.get("/v1/admin/settings"))["data"]
            ledger_before = (
                await customer.get("/v1/customer/wallet/entries")
            ).json()
            async with self.maintenance.uow() as unit:
                await unit.execute(text(f"CREATE DATABASE `{target_schema}`"))
            with TemporaryDirectory(prefix="papilio-recovery-test-") as temp:
                directory = Path(temp)
                settings = RecoverySettings.model_validate(
                    yaml.safe_load(Path("recovery.yml.sample").read_text())
                )
                settings.temporary_directory = directory
                key = secrets.token_urlsafe(32)
                archives = RecoveryArchives(settings, key)
                source_database = MySQLRecovery(self.settings.db.dsn, settings)
                target_database = MySQLRecovery(
                    target_url.render_as_string(hide_password=False), settings
                )
                backup = directory / "snapshot.encrypted"
                raw_config = yaml.safe_dump(self.raw, allow_unicode=True)
                counts_before = await self.table_counts(self.connection)
                payload = await asyncio.to_thread(
                    archives.create, source_database, raw_config, backup
                )
                self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
                encrypted = backup.read_text()
                self.assertNotIn(self.password, encrypted)
                self.assertNotIn("متن خصوصی", encrypted)
                with self.assertRaises(FileExistsError):
                    await asyncio.to_thread(
                        archives.create, source_database, raw_config, backup
                    )
                self.assertEqual(backup.read_text(), encrypted)
                wrong_key = RecoveryArchives(
                    settings, secrets.token_urlsafe(32)
                )
                with self.assertRaises(ValueError):
                    await asyncio.to_thread(
                        wrong_key.restore, backup, target_database
                    )
                damaged = directory / "damaged.encrypted"
                damaged.write_text(encrypted[:-2] + "AA")
                with self.assertRaises(ValueError):
                    await asyncio.to_thread(
                        archives.restore, damaged, target_database
                    )
                async with target.uow() as unit:
                    empty = (
                        await unit.execute(
                            text(
                                "SELECT COUNT(*) "
                                "FROM information_schema.tables "
                                "WHERE table_schema=DATABASE()"
                            )
                        )
                    ).scalar_one()
                    self.assertEqual(empty, 0)
                result = await asyncio.to_thread(
                    archives.restore, backup, target_database
                )
                self.assertEqual(
                    result.schema_revision, payload.schema_revision
                )
                self.assertGreater(result.table_count, 30)
                self.assertEqual(
                    await self.table_counts(target), counts_before
                )
                with self.assertRaisesRegex(ValueError, "empty database"):
                    await asyncio.to_thread(
                        archives.restore, backup, target_database
                    )
                extracted = directory / "recovered.yml"
                await asyncio.to_thread(
                    archives.extract_config, backup, extracted
                )
                self.assertEqual(extracted.stat().st_mode & 0o777, 0o600)
                self.assertEqual(extracted.read_text(), raw_config)
                restored_raw = yaml.safe_load(extracted.read_text())
                restored_raw["db"]["dsn"] = target_url.render_as_string(
                    hide_password=False
                )
                restored_settings = PapilioSettings.model_validate(
                    restored_raw
                )
                restored_app = create_app(
                    restored_settings,
                    providers=infrastructure_providers(restored_settings),
                    middleware=(),
                    docs_url=None,
                )
                transport = httpx.ASGITransport(app=restored_app)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="https://admin.example.com",
                    cookies=self.client.cookies,
                ) as admin:
                    self.assertEqual(
                        (await admin.get("/v1/admin/settings")).json()["data"],
                        policy_before,
                    )
                    login = await admin.post(
                        "/v1/admin/auth/login",
                        headers={"Origin": self.settings.public.admin_origin},
                        json={
                            "username": self.username,
                            "password": self.password,
                        },
                    )
                    self.assertEqual(login.status_code, 200)
                    admin_headers = {
                        "Origin": self.settings.public.admin_origin,
                        "X-CSRF-Token": login.json()["csrf_token"],
                    }
                    replay = await admin.post(
                        "/v1/admin/subscriptions",
                        headers=admin_headers,
                        json=purchase_data,
                    )
                    self.assertEqual(replay.status_code, 200)
                    self.assertEqual(replay.json()["data"]["id"], paid["id"])
                    settled = await admin.post(
                        f"/v1/admin/payments/topups/{topup['id']}/approve",
                        headers=admin_headers,
                        json={"bank_reference": reference},
                    )
                    self.assertEqual(settled.status_code, 200)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url=self.settings.public.customer_portal_origin,
                    cookies=customer.cookies,
                ) as recovered_customer:
                    wallet = await recovered_customer.get(
                        "/v1/customer/wallet"
                    )
                    self.assertEqual(
                        wallet.json()["data"]["balance_rial"], 200000
                    )
                    ledger = await recovered_customer.get(
                        "/v1/customer/wallet/entries"
                    )
                    self.assertEqual(ledger.json(), ledger_before)
                    receipt = await recovered_customer.get(
                        f"{receipt_path}/{receipt_id}"
                    )
                    self.assertEqual(receipt.status_code, 200)
                    self.assertEqual(receipt.content, receipt_before.content)
                    trial_read = await recovered_customer.get(
                        f"/v1/customer/subscriptions/{trial['id']}"
                    )
                    self.assertEqual(
                        trial_read.json()["data"]["entitlement_kind"], "trial"
                    )
                    ticket_read = await recovered_customer.get(
                        f"/v1/customer/support/"
                        f"{ticket.json()['data']['id']}/messages"
                    )
                    self.assertEqual(ticket_read.status_code, 200)
                    self.assertIn(
                        "متن خصوصی",
                        json.dumps(ticket_read.json(), ensure_ascii=False),
                    )
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url=self.settings.public.customer_portal_origin,
                    cookies=other.cookies,
                ) as recovered_other:
                    self.assertEqual(
                        (
                            await recovered_other.get(
                                f"{receipt_path}/{receipt_id}"
                            )
                        ).status_code,
                        404,
                    )
                # Target replay must not change the source ledger.
                unchanged = await customer.get("/v1/customer/wallet/entries")
                self.assertEqual(unchanged.json(), ledger_before)
                reduced = settings.model_copy(update={"max_archive_bytes": 1})
                with self.assertRaises(ValueError):
                    await asyncio.to_thread(
                        RecoveryArchives(reduced, key).read, backup
                    )
        finally:
            await asyncio.gather(customer.aclose(), other.aclose())
            if restored_app is not None:
                await restored_app.state.dishka_container.close()
            await target.dispose()
            async with self.maintenance.uow() as unit:
                await unit.execute(
                    text(f"DROP DATABASE IF EXISTS `{target_schema}`")
                )

    async def test_export_limits_cli_and_partial_restore_recovery(self):
        from papilio.security.crypto import encrypt, hash_sha256

        assert self.settings.db is not None
        target_schema = "papilio_upgrade_test_recovery_" + uuid4().hex[:12]
        target_url = make_url(self.settings.db.dsn).set(database=target_schema)
        async with self.maintenance.uow() as unit:
            await unit.execute(text(f"CREATE DATABASE `{target_schema}`"))
        try:
            with TemporaryDirectory(prefix="papilio-recovery-test-") as temp:
                directory = Path(temp)
                settings = RecoverySettings.model_validate(
                    yaml.safe_load(Path("recovery.yml.sample").read_text())
                )
                settings.temporary_directory = directory
                key = secrets.token_urlsafe(32)
                archives = RecoveryArchives(settings, key)
                source = MySQLRecovery(self.settings.db.dsn, settings)
                target = MySQLRecovery(
                    target_url.render_as_string(hide_password=False), settings
                )
                backup = directory / "snapshot.encrypted"
                payload = await asyncio.to_thread(
                    archives.create,
                    source,
                    yaml.safe_dump(self.raw, allow_unicode=True),
                    backup,
                )
                self.assertEqual(payload.consistency, "online")
                sql_limited = settings.model_copy(update={"max_sql_bytes": 1})
                failed_output = directory / "too-small.encrypted"
                with self.assertRaises(ValueError):
                    await asyncio.to_thread(
                        RecoveryArchives(sql_limited, key).create,
                        MySQLRecovery(self.settings.db.dsn, sql_limited),
                        payload.config_yaml,
                        failed_output,
                    )
                self.assertFalse(failed_output.exists())
                self.assertFalse(list(directory.glob("papilio-recovery-*")))
                corrupt = payload.model_copy(update={"sql_sha256": "0" * 64})
                corrupt_path = directory / "digest.encrypted"
                corrupt_path.write_text(
                    await asyncio.to_thread(
                        encrypt, corrupt.model_dump_json(), key
                    )
                )
                with self.assertRaises(ValueError):
                    await asyncio.to_thread(
                        archives.restore, corrupt_path, target
                    )
                sql = (
                    "CREATE TABLE partial_marker (id INT PRIMARY KEY); "
                    "BROKEN SQL;"
                )
                digest = await asyncio.to_thread(hash_sha256, sql)
                partial = payload.model_copy(
                    update={"sql": sql, "sql_sha256": digest}
                )
                partial_path = directory / "partial.encrypted"
                partial_path.write_text(
                    await asyncio.to_thread(
                        encrypt, partial.model_dump_json(), key
                    )
                )
                with self.assertRaisesRegex(ValueError, "command failed"):
                    await asyncio.to_thread(
                        archives.restore, partial_path, target
                    )
                with self.assertRaisesRegex(ValueError, "empty database"):
                    await asyncio.to_thread(archives.restore, backup, target)
                async with self.maintenance.uow() as unit:
                    await unit.execute(
                        text(f"DROP DATABASE `{target_schema}`")
                    )
                    await unit.execute(
                        text(f"CREATE DATABASE `{target_schema}`")
                    )
                result = await asyncio.to_thread(
                    archives.restore, backup, target
                )
                self.assertEqual(
                    result.schema_revision, payload.schema_revision
                )
                key_path = directory / "key"
                archives.write_private(key_path, key)
                configuration = directory / "recovery.yml"
                configuration.write_text(
                    yaml.safe_dump(settings.model_dump(mode="json"))
                )
                verify = [
                    sys.executable,
                    "scripts/recovery.py",
                    "--recovery-config",
                    str(configuration),
                    "--key-file",
                    str(key_path),
                    "verify",
                    "--archive",
                    str(backup),
                ]
                verified = await asyncio.to_thread(
                    subprocess.run,
                    verify,
                    capture_output=True,
                    text=True,
                    timeout=settings.command_timeout_seconds,
                )
                self.assertEqual(verified.returncode, 0, verified.stderr)
                self.assertIn("Archive verified", verified.stdout)
                self.assertNotIn(key, verified.stdout + verified.stderr)
                key_path.chmod(0o644)
                denied = await asyncio.to_thread(
                    subprocess.run,
                    verify,
                    capture_output=True,
                    text=True,
                    timeout=settings.command_timeout_seconds,
                )
                self.assertEqual(denied.returncode, 1)
                self.assertNotIn(key, denied.stdout + denied.stderr)
                self.assertNotIn("Traceback", denied.stderr)
        finally:
            async with self.maintenance.uow() as unit:
                await unit.execute(
                    text(f"DROP DATABASE IF EXISTS `{target_schema}`")
                )
