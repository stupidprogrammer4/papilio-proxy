from __future__ import annotations

from unittest import TestCase

from bot.presentation.ui import BANNER_PATH, LOGO_PATH, _home_keyboard, _plans_keyboard
from bot.services.subscriptions import Plan


class PresentationTests(TestCase):
    def test_brand_assets_are_available(self) -> None:
        self.assertTrue(BANNER_PATH.is_file())
        self.assertTrue(LOGO_PATH.is_file())

    def test_dynamic_plan_uses_rial_storage_and_toman_display(self) -> None:
        plan = Plan("sample", "پلن آزمایشی", 42, 30, 1_234_560)
        self.assertEqual(plan.price_rial, 1_234_560)
        self.assertEqual(plan.price_toman, 123_456)

    def test_navigation_has_customer_actions(self) -> None:
        home_labels = [button.text for row in _home_keyboard().inline_keyboard for button in row]
        plan_labels = [
            button.text
            for row in _plans_keyboard([Plan("sample", "پلن", 1, 1, 10)]).inline_keyboard
            for button in row
        ]
        self.assertIn("🪄 انتخاب پلن", home_labels)
        self.assertIn("🦋 دربارهٔ پاپیلیو", home_labels)
        self.assertEqual(len(plan_labels), 2)
