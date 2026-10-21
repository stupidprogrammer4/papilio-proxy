"""Operator bot settings through native CSRF, ownership and real PostgreSQL."""

from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from test_nodes import owner_client

pytestmark = pytest.mark.django_db(transaction=True)
TEST_TOKEN = "123456789:placeholder-not-a-real-telegram-token"


def bot_input(label: str = "first-bot", token: str = TEST_TOKEN) -> dict[str, object]:
    return {"request_key": str(uuid4()), "label": label, "token": token}


def test_bot_defaults_creation_and_replay_keep_tokens_private() -> None:
    client = owner_client()
    defaults = client.get("/api/v1/bots/defaults")
    assert defaults.status_code == 200
    assert defaults.json()["runtime"]["poll_timeout_seconds"] == 10
    values = bot_input()
    response = client.post("/api/v1/bots", values, format="json")
    assert response.status_code == 202
    bot = response.json()
    assert bot["verified"] is False and bot["admin_chat_id"] is None
    assert bot["schedule"] == {"enabled": True, "interval_seconds": 10}
    assert bot["revision"] == "1"
    assert TEST_TOKEN not in str(bot)
    assert "token" not in bot and "token_ciphertext" not in bot
    assert client.post("/api/v1/bots", values, format="json").json() == bot
    assert (
        client.post("/api/v1/bots", values | {"label": "different"}, format="json").status_code
        == 409
    )
    assert client.get("/api/v1/bots").json()["count"] == 1
    assert client.post(f"/api/v1/bots/{bot['id']}/pairing").status_code == 409


def test_bot_editor_preserves_credential_and_native_schedule_across_migration_seeds() -> None:
    from django.core.management import call_command

    client = owner_client()
    bot = client.post("/api/v1/bots", bot_input(), format="json").json()
    values = {
        "label": "edited",
        "expected_revision": bot["revision"],
        "runtime": bot["runtime"] | {"pairing_ttl_seconds": 80},
        "schedule": {"enabled": False, "interval_seconds": 19},
    }
    response = client.put(f"/api/v1/bots/{bot['id']}", values, format="json")
    assert response.status_code == 200
    updated = response.json()
    assert updated["revision"] == "2"
    assert updated["runtime"]["pairing_ttl_seconds"] == 80
    assert updated["schedule"] == values["schedule"]
    assert client.put(f"/api/v1/bots/{bot['id']}", values, format="json").status_code == 409
    call_command("migrate", interactive=False, verbosity=0)
    assert client.get(f"/api/v1/bots/{bot['id']}").json() == updated


def test_bot_records_and_pairing_are_scoped_to_each_operator() -> None:
    first, second = owner_client("first"), owner_client("second", superuser=False)
    bot = first.post("/api/v1/bots", bot_input(), format="json").json()
    root = f"/api/v1/bots/{bot['id']}"
    assert second.get(root).status_code == 404
    assert second.post(root + "/pairing").status_code == 404
    assert (
        second.put(
            root,
            {
                "label": "stolen",
                "expected_revision": bot["revision"],
                "runtime": bot["runtime"],
                "schedule": bot["schedule"],
            },
            format="json",
        ).status_code
        == 404
    )
    assert second.get("/api/v1/bots").json()["count"] == 0
    assert "bots:write" in second.get("/api/v1/admin/auth/me").json()["scopes"]
    other = second.post(
        "/api/v1/bots",
        bot_input("other", "987654321:another-placeholder-token-value"),
        format="json",
    )
    assert other.status_code == 202
    duplicate = second.post("/api/v1/bots", bot_input(), format="json")
    assert duplicate.status_code == 409
    assert TEST_TOKEN not in str(duplicate.json())
    User.objects.filter(username="second").update(is_staff=False)
    assert second.get("/api/v1/bots").status_code in {401, 403}


@pytest.mark.parametrize(
    "override",
    [
        {"token": "invalid-token"},
        {"runtime": {"poll_timeout_seconds": 0}},
        {"runtime": {"poll_timeout_seconds": 10, "http_timeout_seconds": 10}},
        {"runtime": {"update_limit": 101}},
        {"runtime": {"pairing_ttl_seconds": 0}},
        {"runtime": {"api_base_url": "http://telegram.example.invalid"}},
        {"runtime": {"api_base_url": "https://api.telegram.org:0"}},
        {"runtime": {"api_base_url": "https://user:password@api.telegram.org"}},
        {"schedule": {"interval_seconds": 0}},
    ],
)
def test_bot_invalid_configuration_creates_no_schedule_or_bot(override: dict[str, object]) -> None:
    client = owner_client()
    response = client.post("/api/v1/bots", bot_input() | override, format="json")
    assert response.status_code == 400
    assert client.get("/api/v1/bots").json()["count"] == 0


def test_bot_collection_has_search_and_complete_pagination() -> None:
    client = owner_client()
    for number in range(3):
        result = client.post(
            "/api/v1/bots",
            bot_input(f"shop-{number}", f"12345678{number}:placeholder-token-value-for-test"),
            format="json",
        )
        assert result.status_code == 202
    first = client.get("/api/v1/bots", {"q": "shop", "page_size": 1}).json()
    second = client.get("/api/v1/bots", {"q": "shop", "page_size": 1, "page": 2}).json()
    assert first["count"] == second["count"] == 3
    assert first["items"][0]["id"] != second["items"][0]["id"]


def test_large_revision_is_transported_without_javascript_rounding() -> None:
    from papilio_panel.modules.bots.models import Bot

    client = owner_client()
    bot = client.post("/api/v1/bots", bot_input(), format="json").json()
    revision = 9007199254740993
    Bot.objects.filter(pk=bot["id"]).update(revision=revision)
    response = client.get(f"/api/v1/bots/{bot['id']}")
    assert response.json()["revision"] == str(revision)


def test_concurrent_bot_creation_leaves_one_bot_and_one_native_schedule() -> None:
    from concurrent.futures import ThreadPoolExecutor

    from django.db import close_old_connections
    from django_celery_beat.models import PeriodicTask

    from papilio_panel.modules.bots.domain import BotCreate, BotTaskName
    from papilio_panel.modules.bots.models import Bot
    from papilio_panel.modules.bots.providers import bots

    user = User.objects.create_superuser(
        username="concurrent-bot-owner", password="isolated-concurrent-password-744!"
    )
    values = BotCreate(actor_id=user.pk, request_key=uuid4(), label="concurrent", token=TEST_TOKEN)

    def create() -> object:
        close_old_connections()
        try:
            return bots.create(values).id
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda _: create(), range(3)))
    assert len(set(results)) == 1
    assert Bot.objects.count() == 1
    assert PeriodicTask.objects.filter(task=BotTaskName.POLL.value).count() == 1


def test_derived_deadline_must_fit_the_native_beat_expiry_field() -> None:
    client = owner_client()
    response = client.post(
        "/api/v1/bots",
        bot_input() | {"runtime": {"poll_timeout_seconds": 1, "http_timeout_seconds": 1000000000}},
        format="json",
    )
    assert response.status_code == 400
    assert client.get("/api/v1/bots").json()["count"] == 0


@pytest.mark.parametrize(
    "partial", [{"runtime": {"http_timeout_seconds": 20}}, {"schedule": {"enabled": False}}]
)
def test_replacing_settings_requires_complete_objects_without_default_resets(
    partial: dict[str, object],
) -> None:
    client = owner_client()
    bot = client.post(
        "/api/v1/bots",
        bot_input()
        | {
            "schedule": {"enabled": False, "interval_seconds": 19},
            "runtime": {"failure_retry_seconds": 77},
        },
        format="json",
    ).json()
    values = {
        "label": bot["label"],
        "expected_revision": bot["revision"],
        "runtime": bot["runtime"],
        "schedule": bot["schedule"],
    } | partial
    response = client.put(f"/api/v1/bots/{bot['id']}", values, format="json")
    assert response.status_code == 400
    assert client.get(f"/api/v1/bots/{bot['id']}").json() == bot
