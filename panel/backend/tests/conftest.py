"""Select capability suites without changing test paths or fixtures."""

import pytest

CAPABILITY_PREFIXES: dict[str, tuple[str, ...]] = {
    "accounts": (
        "auth_security",
        "customer_access",
        "staff_",
        "reseller_accounts",
    ),
    "billing": ("payment_", "sms_", "wallet", "reseller_billing"),
    "sales": (
        "admin_plan",
        "checkout_",
        "customer_checkout",
        "configured_checkout",
        "fulfillment",
        "loyalty",
        "plan_",
        "purchased_ip_policy",
        "renewal",
        "reseller_catalog",
        "subscription_control",
        "trials",
    ),
    "network": (
        "configuration",
        "core_",
        "ip_",
        "managed_",
        "node_",
        "openvpn",
        "panel_configuration",
        "qr_",
        "real_core",
        "real_tunnel",
        "runtime_agent",
        "server_json",
        "sing_box",
        "usage_",
    ),
    "operations": (
        "attention_filters",
        "automation_",
        "notifications",
        "subscription_alert",
    ),
    "bot": ("bot_",),
    "support": ("support",),
    "platform": ("event_loop", "foundations", "performance", "recovery"),
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Attach capability tags; execution-boundary tags remain independent."""
    for item in items:
        responsibility = item.path.stem.removeprefix("test_")
        for capability, prefixes in CAPABILITY_PREFIXES.items():
            if responsibility.startswith(prefixes):
                item.add_marker(capability)
