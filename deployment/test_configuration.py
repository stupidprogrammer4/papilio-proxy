"""Installer identity preservation and origin validation."""

import base64
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import configure


class ConfigurationTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="papilio deploy ")
        self.addCleanup(self.directory.cleanup)
        self.state = Path(self.directory.name) / "state"

    def options(self, *extra):
        return configure.parser().parse_args(
            [
                "--state-dir",
                str(self.state),
                "--public-url",
                "http://127.0.0.1:18080",
                "--http-port",
                "18080",
                "--owner-username",
                "fixture_owner",
                *extra,
            ]
        )

    def generate(self, options, answers):
        with (
            patch.object(configure.getpass, "getpass", side_effect=answers),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            configure.configure(options)

    def snapshot(self):
        return {
            str(p.relative_to(self.state)): p.read_bytes()
            for p in self.state.rglob("*")
            if p.is_file()
        }

    def test_repeat_preserves_secrets_and_edited_native_policy(self):
        args = self.options()
        self.generate(args, ["Fixture-private-105", "Fixture-private-105"])
        import yaml

        path = self.state / "config.yml"
        raw = yaml.safe_load(path.read_text())
        raw["operations"]["payment_batch_size"] = 17
        path.write_text(yaml.safe_dump(raw, allow_unicode=True))
        with (self.state / "compose.env").open("a") as saved:
            saved.write("MYSQL_IMAGE=mysql:8.4.10\n")
        before = self.snapshot()
        self.generate(args, [])
        self.assertEqual(before, self.snapshot())
        self.assertFalse(raw["core_runtime"]["allow_start"])
        self.assertEqual(raw["core_provisioning"]["mode"], "disabled")
        self.assertEqual(raw["core_usage"]["mode"], "disabled")
        self.assertEqual(
            raw["rate_limit"]["trusted_proxies"], ["172.30.58.254"]
        )
        if os.name != "nt":
            self.assertTrue(
                all(
                    p.stat().st_mode & 0o077 == 0
                    for p in self.state.rglob("*")
                    if p.is_file()
                )
            )

    def test_bot_enable_preserves_existing_identity(self):
        args = self.options(
            "--public-url",
            "https://fixture.example.com",
            "--http-port",
            "80",
            "--https-port",
            "443",
        )
        self.generate(args, ["Fixture-private-105", "Fixture-private-105"])
        before = self.snapshot()
        args.enable_bot = True
        self.generate(args, ["123456789:FixtureFakeTokenNotReal_Only"])
        after = self.snapshot()
        for name in before.keys() - {"compose.env", "bot.env", "Caddyfile", "web.env"}:
            self.assertEqual(before[name], after[name])
        web = configure.parse_env(after["web.env"].decode())
        self.assertEqual(
            base64.b64decode(web["PAPILIO_CADDYFILE_BASE64"]), after["Caddyfile"]
        )
        old = configure.parse_env(before["bot.env"].decode())
        new = configure.parse_env(after["bot.env"].decode())
        self.assertEqual(
            old["TELEGRAM_WEBHOOK_SECRET"], new["TELEGRAM_WEBHOOK_SECRET"]
        )
        self.assertEqual(
            new["TELEGRAM_WEBHOOK_PUBLIC_URL"],
            "https://fixture.example.com/telegram/webhook",
        )
        sys.path.insert(0, str(configure.ROOT / "bot"))
        from papilio_telegram.config import BotSettings

        with patch.dict(os.environ, new, clear=True):
            settings = BotSettings.from_environment()
        self.assertEqual(settings.listen_port, 8020)
        self.assertEqual(settings.api_url, "http://api:8000")
        self.generate(args, [])
        self.assertEqual(after, self.snapshot())

    def test_invalid_origins_and_ports_leave_no_state(self):
        cases = [
            ("--http-port", "18081"),
            ("--https-port", "18080"),
            ("--public-url", "http://remote.example.com:18080"),
            ("--public-url", "http://user:secret@localhost:18080"),
            ("--public-url", "https://fixture.example.com/path"),
            ("--enable-bot",),
            ("--bind-address", "::1"),
            ("--network-subnet", "172.30.58.0/29"),
            ("--project-name", "x" * 118),
        ]
        for options in cases:
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.generate(self.options(*options), [])
            self.assertFalse(self.state.exists())

    def test_origin_matches_browser_default_port_normalization(self):
        self.assertEqual(
            configure.public_origin("https://Fixture.Example.com:443/", False),
            "https://fixture.example.com",
        )
        self.assertEqual(
            configure.public_origin("http://localhost:80/", False),
            "http://localhost",
        )
        with self.assertRaises(ValueError):
            configure.public_origin("http://[::1]:18080", False)

    def test_default_project_identity_depends_on_host_state(self):
        first = self.options()
        second = self.options("--host-state-dir", str(self.state) + "-other")
        origin = "http://127.0.0.1:18080"
        left = configure.runtime_values(first, origin, self.state)
        right = configure.runtime_values(second, origin, self.state)
        self.assertNotEqual(left["PROJECT_NAME"], right["PROJECT_NAME"])

    def test_partial_or_mismatched_state_is_not_replaced(self):
        args = self.options()
        self.generate(args, ["Fixture-private-105", "Fixture-private-105"])
        (self.state / "secrets/mysql-password").unlink()
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.generate(args, [])
        self.assertEqual(before, self.snapshot())


if __name__ == "__main__":
    unittest.main()
