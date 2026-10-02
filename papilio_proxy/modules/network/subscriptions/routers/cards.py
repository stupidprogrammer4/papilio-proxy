from datetime import datetime
from html import escape
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

from papilio_proxy.modules.network.subscriptions.domain.entities import SubscriptionAccess


def expiry_label(value: datetime) -> str:
    return value.astimezone(ZoneInfo("Asia/Tehran")).strftime("%Y/%m/%d · %H:%M")


def traffic_label(value: int) -> str:
    if value < 1024**3:
        return f"{value / 1024**2:.0f} مگابایت"
    return f"{value / 1024**3:.1f}".rstrip("0").rstrip(".") + " گیگابایت"


def subscription_url(public_base: str, access: SubscriptionAccess) -> str:
    parsed = urlsplit(public_base)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Invalid public subscription origin")
    return f"{public_base.rstrip('/')}/s/{access.token}#{quote(access.profile_name[:40], safe='')}"


def delivery_caption(access: SubscriptionAccess, url: str) -> str:
    return (
        "🦋 <b>اشتراکت آماده‌ست!</b>\n\n"
        f"{escape(access.plan_emoji)} <b>{escape(access.plan_title[:80])}</b>\n"
        f"📦 حجم: {traffic_label(access.traffic_limit_bytes)}\n"
        f"📊 مصرف: {traffic_label(access.traffic_used_bytes)} · مانده: {traffic_label(access.traffic_remaining_bytes)}\n"
        f"🗓 اعتبار تا: {expiry_label(access.expires_at)}\n\n"
        f"🔗 <b>لینک اشتراک اختصاصی تو</b>\n<code>{escape(url)}</code>\n\n"
        "📲 لینک را کپی کن و در «افزودن اشتراک» برنامه وارد کن، یا QR را اسکن کن.\n"
        "🔐 لینک اشتراکت را برای دیگران نفرست."
    )
