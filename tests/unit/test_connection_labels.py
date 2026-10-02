import json
from base64 import b64decode
from dataclasses import replace
from unittest import TestCase
from urllib.parse import unquote, urlsplit

from papilio_proxy.modules.network.subscriptions.routers.views import connection_links
from tests.unit.test_access import MemoryAccessRepository


class ConnectionLabelTests(TestCase):
    def test_friendly_labels_preserve_all_connection_credentials_and_parameters(self) -> None:
        access = replace(
            MemoryAccessRepository().access,
            hysteria_link="hysteria2://secret@node.example:443?obfs=salamander&obfs-password=key#old",
            plan_title="تست خرید",
            plan_emoji="🧪",
        )
        links = connection_links(access)
        for original, renamed, name in zip(
            (access.hysteria_link, access.vless_link),
            links[:2],
            ("پیشنهادی", "مسیر ۱"),
            strict=True,
        ):
            assert original is not None
            self.assertEqual(
                urlsplit(original)._replace(fragment=""), urlsplit(renamed)._replace(fragment="")
            )
            self.assertIn(name, unquote(urlsplit(renamed).fragment))
            self.assertIn(access.profile_name, unquote(urlsplit(renamed).fragment))
        old = json.loads(b64decode(access.vmess_link.removeprefix("vmess://")))
        new = json.loads(b64decode(links[2].removeprefix("vmess://")))
        self.assertIn("مسیر ۲", new.pop("ps"))
        old.pop("ps", None)
        self.assertEqual(old, new)
