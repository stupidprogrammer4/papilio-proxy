from __future__ import annotations

import os
from unittest import TestCase
from unittest.mock import patch

from bot.core.config import ConfigurationError, Settings


class SettingsTests(TestCase):
    def test_telegram_token_has_precedence_over_legacy_token(self) -> None:
        with patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "preferred",
                "BOT_TOKEN": "legacy",
                "DATABASE_URL": "mysql+aiomysql://user:pass@db/papilio",
            },
            clear=True,
        ):
            settings = Settings.from_environment()
        self.assertEqual(settings.bot_token, "preferred")
        self.assertEqual(settings.database_url, "mysql+aiomysql://user:pass@db/papilio")

    def test_bot_token_is_required_only_for_bot_runtime(self) -> None:
        with patch.dict(
            os.environ, {"DATABASE_URL": "mysql+aiomysql://user:pass@db/papilio"}, clear=True
        ):
            settings = Settings.from_environment(require_token=False)
            self.assertIsNone(settings.bot_token)
            with self.assertRaises(ConfigurationError):
                Settings.from_environment()
