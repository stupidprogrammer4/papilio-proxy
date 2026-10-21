"""Real DB/task adapters and controlled external Telegram behavior."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from django.db import close_old_connections
from django.utils import timezone
from telegram_server import TelegramServer
from test_bots import bot_input
from test_nodes import owner_client

from papilio_panel.config.celery import app
from papilio_panel.modules.bots.domain import BotTaskName
from papilio_panel.modules.bots.models import Bot, TelegramInbox

pytestmark = pytest.mark.django_db(transaction=True)


def poll(bot_id: str) -> None:
    app.tasks[BotTaskName.POLL.value].apply(kwargs={"bot_id": bot_id}, throw=True)


def test_pairing_issued_during_active_poll_is_consumed_and_not_stored_as_a_secret() -> None:
    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        response = client.post(
            "/api/v1/bots",
            bot_input()
            | {
                "runtime": {
                    "api_base_url": address,
                    "poll_timeout_seconds": 1,
                    "http_timeout_seconds": 6,
                }
            },
            format="json",
        )
        assert response.status_code == 202
        bot = response.json()
        root = f"/api/v1/bots/{bot['id']}"
        poll(bot["id"])
        assert client.get(root).json()["verified"] is True
        server.hold()

        def independent_poll() -> None:
            close_old_connections()
            try:
                poll(bot["id"])
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(independent_poll)
            assert server.entered.wait(timeout=3)
            grant = client.post(root + "/pairing")
            assert grant.status_code == 200
            assert grant["Cache-Control"] == "private, no-store"
            parameter = parse_qs(urlsplit(grant.json()["url"]).query)["start"][0]
            server.push(10, "/start " + parameter)
            server.release.set()
            future.result(timeout=10)
        assert client.get(root).json()["admin_chat_id"] == 456789
        assert parameter not in json.dumps(TelegramInbox.objects.get(update_id=10).payload)
        assert Bot.objects.get(pk=bot["id"]).pairing_digest is None
        server.push(11, "/start " + parameter, chat_id=999111)
        poll(bot["id"])
        assert client.get(root).json()["admin_chat_id"] == 456789
        poll(bot["id"])
        assert TelegramInbox.objects.count() == 2


def test_expired_group_and_foreign_bot_pairing_do_not_grant_access() -> None:
    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        runtime = {"api_base_url": address, "poll_timeout_seconds": 1, "http_timeout_seconds": 6}
        first = client.post(
            "/api/v1/bots", bot_input() | {"runtime": runtime}, format="json"
        ).json()
        second = client.post(
            "/api/v1/bots",
            bot_input("second", "987654321:placeholder-token-value-for-second")
            | {"runtime": runtime},
            format="json",
        ).json()
        poll(first["id"])
        poll(second["id"])
        first_root, second_root = f"/api/v1/bots/{first['id']}", f"/api/v1/bots/{second['id']}"
        grant = client.post(first_root + "/pairing").json()
        parameter = parse_qs(urlsplit(grant["url"]).query)["start"][0]
        server.push(1, "/start " + parameter, chat_id=-123, sender_id=456789, kind="group")
        poll(first["id"])
        assert client.get(first_root).json()["admin_chat_id"] is None
        server.push(2, "/start " + parameter)
        poll(second["id"])
        assert client.get(second_root).json()["admin_chat_id"] is None
        Bot.objects.filter(pk=first["id"]).update(
            pairing_expires_at=timezone.now() - timedelta(seconds=1)
        )
        poll(first["id"])
        assert client.get(first_root).json()["admin_chat_id"] is None


def test_existing_webhook_is_reported_without_mutating_telegram() -> None:
    server = TelegramServer()
    server.webhook = "https://existing.example.invalid/telegram"
    with server.running() as address:
        client = owner_client()
        result = client.post(
            "/api/v1/bots", bot_input() | {"runtime": {"api_base_url": address}}, format="json"
        ).json()
        poll(result["id"])
        current = client.get(f"/api/v1/bots/{result['id']}").json()
        assert current["verified"] is False
        assert current["last_error_code"] == "webhook_configured"
        assert [call[0] for call in server.calls] == ["getMe", "getWebhookInfo"]
        assert TelegramInbox.objects.count() == 0


def test_configuration_change_discards_old_poll_and_releases_its_lease() -> None:
    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        created = client.post(
            "/api/v1/bots",
            bot_input()
            | {
                "runtime": {
                    "api_base_url": address,
                    "poll_timeout_seconds": 1,
                    "http_timeout_seconds": 6,
                }
            },
            format="json",
        ).json()
        root = f"/api/v1/bots/{created['id']}"
        poll(created["id"])
        server.hold()

        def independent_poll() -> None:
            close_old_connections()
            try:
                poll(created["id"])
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(independent_poll)
            assert server.entered.wait(timeout=3)
            current = client.get(root).json()
            changed = client.put(
                root,
                {
                    "label": "changed",
                    "expected_revision": current["revision"],
                    "runtime": current["runtime"],
                    "schedule": current["schedule"],
                },
                format="json",
            )
            assert changed.status_code == 200
            server.push(9, "A retained customer message")
            server.release.set()
            future.result(timeout=10)
        stale = Bot.objects.get(pk=created["id"])
        assert stale.next_update_id == 0 and stale.verified_revision is None
        assert not TelegramInbox.objects.exists()
        assert stale.lease_token is None and stale.lease_until is None
        poll(created["id"])
        assert client.get(root).json()["next_update_id"] == "10"
        assert TelegramInbox.objects.count() == 1


def test_inbox_write_failure_does_not_advance_or_acknowledge_updates() -> None:
    from typing import Any
    from uuid import UUID

    from django.db import OperationalError, connection

    from papilio_panel.modules.bots.providers import polling

    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        created = client.post(
            "/api/v1/bots",
            bot_input()
            | {
                "runtime": {
                    "api_base_url": address,
                    "poll_timeout_seconds": 1,
                    "http_timeout_seconds": 6,
                }
            },
            format="json",
        ).json()
        server.push(7, "Customer message before a worker failure")

        def fail_inbox(execute: Any, sql: str, params: Any, many: bool, context: Any) -> Any:
            if sql.startswith("INSERT") and TelegramInbox._meta.db_table in sql:
                raise OperationalError("Explicit test-owned inbox fault")
            return execute(sql, params, many, context)

        with connection.execute_wrapper(fail_inbox), pytest.raises(OperationalError):
            polling.poll(UUID(created["id"]))
        state = Bot.objects.get(pk=created["id"])
        assert state.next_update_id == 0 and state.verified_revision is None
        assert not TelegramInbox.objects.exists()
        # Simulate the bounded expiry after a worker dies before completion.
        Bot.objects.filter(pk=created["id"]).update(
            lease_until=timezone.now() - timedelta(seconds=1)
        )
        poll(created["id"])
        poll(created["id"])
        assert TelegramInbox.objects.filter(update_id=7).count() == 1
        offsets = [
            parameters["offset"] for method, parameters in server.calls if method == "getUpdates"
        ]
        assert offsets == [0, 0, 8]


def test_telegram_retry_delay_prevents_immediate_api_calls() -> None:
    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        created = client.post(
            "/api/v1/bots",
            bot_input()
            | {
                "runtime": {
                    "api_base_url": address,
                    "poll_timeout_seconds": 1,
                    "http_timeout_seconds": 6,
                }
            },
            format="json",
        ).json()
        root = f"/api/v1/bots/{created['id']}"
        poll(created["id"])
        server.next_error_status = 429
        poll(created["id"])
        assert client.get(root).json()["last_error_code"] == "rate_limited"
        calls = len(server.calls)
        poll(created["id"])
        assert len(server.calls) == calls
        assert client.get(root).json()["retry_at"] is not None


@pytest.mark.parametrize("size", [1, 100])
def test_update_batch_uses_one_native_inbox_insert(size: int) -> None:
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        created = client.post(
            "/api/v1/bots",
            bot_input()
            | {
                "runtime": {
                    "api_base_url": address,
                    "poll_timeout_seconds": 1,
                    "http_timeout_seconds": 6,
                }
            },
            format="json",
        ).json()
        for identifier in range(size):
            server.push(identifier, "retained customer message")
        with CaptureQueriesContext(connection) as captured:
            poll(created["id"])
        inserts = [
            query
            for query in captured.captured_queries
            if query["sql"].startswith("INSERT") and TelegramInbox._meta.db_table in query["sql"]
        ]
        assert len(inserts) == 1
        assert TelegramInbox.objects.count() == size
        assert len([method for method, _ in server.calls if method == "getUpdates"]) == 1


def test_revoked_operator_cannot_poll_telegram() -> None:
    from django.contrib.auth.models import User

    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        created = client.post(
            "/api/v1/bots", bot_input() | {"runtime": {"api_base_url": address}}, format="json"
        ).json()
        User.objects.filter(username="node-owner").update(is_staff=False)
        poll(created["id"])
        assert server.calls == []
        assert TelegramInbox.objects.count() == 0
        state = Bot.objects.get(pk=created["id"])
        assert state.last_error_code == "access_revoked" and state.next_update_id == 0


def test_poll_claim_reads_offset_committed_by_a_concurrent_preceding_poll() -> None:
    from typing import Any

    from django.db import connection

    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        created = client.post(
            "/api/v1/bots",
            bot_input()
            | {
                "runtime": {
                    "api_base_url": address,
                    "poll_timeout_seconds": 1,
                    "http_timeout_seconds": 6,
                }
            },
            format="json",
        ).json()
        server.push(1, "customer message")

        def preceding_poll() -> None:
            close_old_connections()
            try:
                poll(created["id"])
            finally:
                close_old_connections()

        def commit_before_claim(
            execute: Any, sql: str, params: Any, many: bool, context: Any
        ) -> Any:
            if sql.startswith(f'UPDATE "{Bot._meta.db_table}" SET "lease_token" = %s'):
                with ThreadPoolExecutor(max_workers=1) as executor:
                    executor.submit(preceding_poll).result(timeout=10)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(commit_before_claim):
            poll(created["id"])
        offsets = [
            parameters["offset"] for method, parameters in server.calls if method == "getUpdates"
        ]
        assert offsets == [0, 2]
        assert TelegramInbox.objects.count() == 1


def test_ordinary_text_matching_pairing_shape_is_not_erased() -> None:
    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        created = client.post(
            "/api/v1/bots", bot_input() | {"runtime": {"api_base_url": address}}, format="json"
        ).json()
        ordinary_text = "gift code: pair_" + "a" * 32
        server.push(30, ordinary_text)
        poll(created["id"])
        assert TelegramInbox.objects.get(update_id=30).payload["message"]["text"] == ordinary_text
