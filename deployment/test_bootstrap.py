"""Native bootstrap and owner replay against isolated local MySQL."""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import configure
import pymysql
import yaml
from sqlalchemy.engine import make_url


@unittest.skipUnless(
    os.getenv("PAPILIO_TEST_DATABASE_URL"), "local MySQL required"
)
class BootstrapTest(unittest.TestCase):
    def test_fresh_owner_replay_and_upgrade_refusal(self):
        url = make_url(os.environ["PAPILIO_TEST_DATABASE_URL"])
        self.assertIn(url.host, ("127.0.0.1", "localhost"))
        assert url.host is not None
        assert url.username is not None
        assert url.password is not None
        schema = "papilio_deploy_test_" + uuid4().hex[:12]
        connection = pymysql.connect(
            host=url.host,
            port=url.port or 3306,
            user=url.username,
            password=url.password,
            autocommit=True,
        )
        self.addCleanup(connection.close)
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE `{schema}`")
        self.addCleanup(self.drop_schema, connection, schema)
        with tempfile.TemporaryDirectory(
            prefix="papilio bootstrap "
        ) as folder:
            state = Path(folder) / "state"
            args = configure.parser().parse_args(
                [
                    "--state-dir",
                    str(state),
                    "--public-url",
                    "http://127.0.0.1:18080",
                    "--http-port",
                    "18080",
                    "--owner-username",
                    "fixture_owner",
                ]
            )
            with (
                patch.object(
                    configure.getpass,
                    "getpass",
                    side_effect=["Fixture-private-105", "Fixture-private-105"],
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                configure.configure(args)
            settings = state / "config.yml"
            raw = yaml.safe_load(settings.read_text())
            raw["db"]["dsn"] = url.set(database=schema).render_as_string(
                hide_password=False
            )
            settings.write_text(yaml.safe_dump(raw))
            env = {
                **os.environ,
                "PAPILIO_CONFIG": str(settings),
                "OWNER_USERNAME": "fixture_owner",
                "OWNER_PASSWORD_FILE": str(state / "secrets/owner-password"),
            }
            command = [
                sys.executable,
                str(Path(__file__).with_name("bootstrap.py")),
            ]
            first = subprocess.run(
                command, env=env, capture_output=True, timeout=90
            )
            self.assertEqual(
                first.returncode, 0, "Fresh native bootstrap failed"
            )
            connection.select_db(schema)
            original = self.read_owner(connection)
            self.assertEqual(len(original), 1)
            with connection.cursor() as cursor:
                cursor.execute("SELECT scope FROM tbl_staff_grants")
                self.assertIn(("*",), cursor.fetchall())
            (state / "secrets/owner-password").write_text(
                "Changed-fixture-password"
            )
            replay = subprocess.run(
                command, env=env, capture_output=True, timeout=90
            )
            self.assertEqual(replay.returncode, 0, "Bootstrap replay failed")
            self.assertEqual(original, self.read_owner(connection))
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE alembic_version SET version_num=%s",
                    ("prior_schema",),
                )
            refused = subprocess.run(
                command, env=env, capture_output=True, timeout=90
            )
            self.assertNotEqual(refused.returncode, 0)
            self.assertEqual(original, self.read_owner(connection))
            with connection.cursor() as cursor:
                cursor.execute("SELECT version_num FROM alembic_version")
                self.assertEqual(cursor.fetchall(), (("prior_schema",),))

    @staticmethod
    def read_owner(connection):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, username, password_hash FROM tbl_staff ORDER BY id"
            )
            return cursor.fetchall()

    @staticmethod
    def drop_schema(connection, schema):
        with connection.cursor() as cursor:
            cursor.execute(f"DROP DATABASE `{schema}`")


if __name__ == "__main__":
    unittest.main()
