from __future__ import annotations

import base64
import json
from html import escape
from pathlib import Path
from string import Template
from urllib.parse import quote, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from bot.models.access import SubscriptionAccess

ASSETS = Path(__file__).with_name("static")
PAGE = Template((ASSETS / "subscription.html").read_text())


def connection_links(access: SubscriptionAccess) -> list[str]:
    """Change display labels only; preserve transport credentials and parameters."""
    result: list[str] = []
    for link, icon, protocol in (
        (access.hysteria_link, "🚀", "Hysteria2"),
        (access.vless_link, "⚡", "VLESS"),
        (access.vmess_link, "🌐", "VMess"),
    ):
        if not link:
            continue
        label = f"{icon} {access.profile_name} · {protocol}"
        parsed = urlsplit(link)
        if protocol == "VMess":
            payload = json.loads(base64.b64decode(parsed.netloc, validate=True))
            payload["ps"] = label
            encoded = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()
            result.append("vmess://" + encoded)
        else:
            result.append(urlunsplit(parsed._replace(fragment=quote(label, safe=""))))
    return result


def subscription_page(access: SubscriptionAccess, public_base: str | None) -> str:
    percent = min(100, access.traffic_used_bytes * 100 // access.traffic_limit_bytes)
    zone = ZoneInfo("Asia/Tehran")
    expiry = access.expires_at.astimezone(zone).strftime("%Y/%m/%d · %H:%M")
    measured = access.last_measured_at
    last_update = measured.astimezone(zone).strftime("%H:%M:%S") if measured else "—"
    subscription = f"{public_base}/s/{access.token}#{quote(access.profile_name)}" if public_base else ""
    return PAGE.substitute(
        title=escape(access.profile_name), emoji=escape(access.plan_emoji),
        plan=escape(access.plan_title), percent=percent,
        used=f"{access.traffic_used_bytes / 1024**3:.2f}",
        remaining=f"{access.traffic_remaining_bytes / 1024**3:.2f}",
        total=f"{access.traffic_limit_bytes / 1024**3:.2f}",
        expires=escape(expiry), measured=escape(last_update),
        subscription=escape(subscription, quote=True),
        import_url=escape("hiddify://import/" + subscription, quote=True),
        protocols="🚀 Hysteria2 · ⚡ VLESS · 🌐 VMess" if access.hysteria_link else "⚡ VLESS · 🌐 VMess",
    )
