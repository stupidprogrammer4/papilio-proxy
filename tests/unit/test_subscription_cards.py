import re
from dataclasses import replace
from datetime import UTC, datetime
from html import unescape
from unittest import TestCase
from urllib.parse import unquote, urlsplit

from papilio_proxy.modules.network.subscriptions.routers.cards import (
    delivery_caption,
    expiry_label,
    subscription_url,
    traffic_label,
)
from papilio_proxy.modules.sales.subscriptions.routers.telegram import _access_keyboard
from tests.unit.test_access import MemoryAccessRepository


class SubscriptionCardTests(TestCase):
    def test_delivery_shows_quota_usage_and_tehran_expiry_without_claiming_payment(self) -> None:
        access = replace(
            MemoryAccessRepository().access,
            traffic_limit_bytes=1024**3,
            uplink_bytes=128 * 1024**2,
            downlink_bytes=128 * 1024**2,
            expires_at=datetime(2026, 10, 3, 20, 0, tzinfo=UTC),
            plan_title="تست <خصوصی> & اتصال",
            plan_emoji="🧪",
        )
        url = subscription_url("https://sub.example/", access)
        caption = delivery_caption(access, url)
        for value in (
            "🧪",
            "لینک اشتراک",
            "1 گیگابایت",
            "256 مگابایت",
            "768 مگابایت",
            "2026/10/03 · 23:30",
            "&lt;خصوصی&gt; &amp;",
            url,
        ):
            self.assertIn(value, caption)
        self.assertNotIn("پرداخت", caption)
        self.assertNotIn("hysteria", caption.lower())
        self.assertEqual(expiry_label(access.expires_at), "2026/10/03 · 23:30")
        self.assertEqual(traffic_label(0), "0 مگابایت")

    def test_delivery_caption_fits_telegram_with_long_plan_name(self) -> None:
        access = replace(MemoryAccessRepository().access, plan_title="🦋" * 100)
        caption = delivery_caption(access, subscription_url("https://bot.amupouya.org", access))
        displayed = unescape(re.sub(r"</?(?:b|code)>", "", caption))
        self.assertLessEqual(len(displayed.encode("utf-16-le")) // 2, 1024)

    def test_subscription_copy_keeps_name_and_usage_link_has_no_fragment(self) -> None:
        access = MemoryAccessRepository().access
        url = subscription_url("https://sub.example", access)
        keyboard = _access_keyboard(access.subscription_id, url, True)
        copy = keyboard.inline_keyboard[0][0]
        assert copy.copy_text is not None
        self.assertEqual(copy.copy_text.text, url)
        self.assertIn("Papilio", unquote(urlsplit(url).fragment))
        usage = next(button for row in keyboard.inline_keyboard for button in row if button.url)
        self.assertEqual(usage.url, "https://sub.example/usage/private-token")
        self.assertEqual(copy.style, "success")
        self.assertEqual(usage.style, "primary")

    def test_subscription_origin_rejects_untrusted_or_non_https_values(self) -> None:
        access = MemoryAccessRepository().access
        for origin in (
            "http://sub.example",
            "https://a:b@sub.example",
            "https://sub.example/a",
            "https://sub.example?q=a",
        ):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                subscription_url(origin, access)
