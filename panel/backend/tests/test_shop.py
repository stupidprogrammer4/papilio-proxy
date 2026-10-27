"""Native owner-scoped bot shop configuration and sender-bound customer contracts."""

from uuid import uuid4

import pytest
from rest_framework.test import APIClient
from test_bots import bot_input
from test_nodes import owner_client

pytestmark = pytest.mark.django_db(transaction=True)


def shop_bot(client: APIClient) -> dict:
    response = client.post("/api/v1/bots", bot_input(), format="json")
    assert response.status_code == 202
    return response.json()


def test_shop_settings_are_owned_complete_and_persist_operator_choices() -> None:
    client = owner_client()
    assert {"bot-shop:read", "bot-shop:write"} <= set(
        client.get("/api/v1/admin/auth/me").json()["scopes"]
    )
    bot = shop_bot(client)
    root = f"/api/v1/bots/{bot['id']}/shop"
    assert client.get(root).status_code == 404
    defaults = client.get("/api/v1/bot-shop-defaults")
    assert defaults.status_code == 200
    assert defaults.json()["flows"] == {
        "catalogue": True,
        "wallet": True,
        "orders": True,
        "help": True,
    }
    definition = defaults.json() | {
        "enabled": True,
        "public_origin": "http://panel.example.invalid",
        "locale": "en",
        "flows": {"catalogue": False, "wallet": True, "orders": False, "help": True},
    }
    created = client.post(root, definition, format="json")
    assert created.status_code == 201
    assert created.json()["revision"] == "1"
    replacement = definition | {"enabled": False, "page_size": 3, "retry_seconds": 17}
    changed = client.put(root, {"expected_revision": "1", **replacement}, format="json")
    assert changed.status_code == 200
    assert client.get(root).json()["definition"] == replacement
    invalid_flows = replacement | {
        "flows": {"catalogue": "nope", "wallet": True, "orders": False, "help": True}
    }
    assert (
        client.put(root, {"expected_revision": "2", **invalid_flows}, format="json").status_code
        == 400
    )
    assert client.get(root).json()["definition"] == replacement
    legacy_replacement = replacement.copy()
    del legacy_replacement["flows"]
    preserved = client.put(root, {"expected_revision": "2", **legacy_replacement}, format="json")
    assert preserved.status_code == 200
    assert preserved.json()["definition"]["flows"] == replacement["flows"]
    assert (
        client.put(root, {"expected_revision": "1", **definition}, format="json").status_code == 409
    )
    assert client.post(root, definition, format="json").status_code == 409
    omitted = {"expected_revision": "3", **replacement}
    del omitted["enabled"]
    assert client.put(root, omitted, format="json").status_code == 400
    other = owner_client("other-shop-owner")
    assert other.get(root).status_code == 404
    assert other.post(root, definition, format="json").status_code == 404
    staff = owner_client("shop-staff", superuser=False)
    assert "bot-shop:read" not in staff.get("/api/v1/admin/auth/me").json()["scopes"]
    assert staff.get("/api/v1/bot-shop-defaults").status_code == 401
    assert staff.get(root).status_code == 401
    assert client.get(f"/api/v1/bots/{uuid4()}/shop").status_code == 404


def test_shop_settings_add_new_locales_without_replacing_existing_texts() -> None:
    from papilio_panel.modules.shop.models import ShopConfiguration

    client = owner_client("localized-shop-owner")
    bot = shop_bot(client)
    root = f"/api/v1/bots/{bot['id']}/shop"
    definition = client.get("/api/v1/bot-shop-defaults").json() | {
        "public_origin": "https://shop.example.invalid",
        "enabled": True,
        "locale": "en",
    }
    assert client.post(root, definition, format="json").status_code == 201
    legacy_texts = {
        "en": definition["texts"]["en"] | {"welcome": "Existing English $name"},
        "fa": definition["texts"]["fa"] | {"welcome": "متن فارسی ذخیره‌شده $name"},
    }
    ShopConfiguration.objects.filter(bot_id=bot["id"]).update(texts=legacy_texts)

    response = client.get(root)
    assert response.status_code == 200
    saved = response.json()["definition"]
    assert set(saved["texts"]) == {"en", "fa", "ru", "zh"}
    assert saved["texts"]["en"]["welcome"] == "Existing English $name"
    assert saved["texts"]["fa"]["welcome"] == "متن فارسی ذخیره‌شده $name"

    saved["locale"] = "zh"
    saved["texts"]["zh"]["welcome"] = "已保存的中文 $name"
    changed = client.put(
        root, {"expected_revision": response.json()["revision"], **saved}, format="json"
    )
    assert changed.status_code == 200
    persisted = changed.json()["definition"]["texts"]
    assert set(persisted) == {"en", "fa", "ru", "zh"}
    assert persisted["en"]["welcome"] == "Existing English $name"
    assert persisted["fa"]["welcome"] == "متن فارسی ذخیره‌شده $name"
    assert persisted["zh"]["welcome"] == "已保存的中文 $name"


def test_shop_schedule_reinitialization_preserves_operator_pause_and_interval() -> None:
    from papilio_panel.modules.shop.infra.schedules import initialize_shop

    client = owner_client()
    schedule = next(
        row for row in client.get("/api/v1/system/schedules").json() if row["key"] == "shop-outbox"
    )
    response = client.put(
        "/api/v1/system/schedules/shop-outbox",
        {"enabled": False, "interval_seconds": 17, "expected_changed_at": schedule["changed_at"]},
        format="json",
    )
    assert response.status_code == 200
    initialize_shop(sender=object())
    current = next(
        row for row in client.get("/api/v1/system/schedules").json() if row["key"] == "shop-outbox"
    )
    assert current["enabled"] is False and current["interval_seconds"] == 17
