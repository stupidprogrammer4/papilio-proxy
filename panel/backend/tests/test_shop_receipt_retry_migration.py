"""Upgrade real nonempty work without replaying old failures or resetting policies."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from telegram_server import TelegramServer
from test_nodes import owner_client
from test_shop_customers import configured_event

from papilio_panel.modules.bots.models import TelegramInbox
from papilio_panel.modules.shop.models import InboxWork
from papilio_panel.modules.shop.providers import execution

pytestmark = pytest.mark.django_db(transaction=True)


def test_receipt_retry_upgrade_retains_prior_failure_and_operator_settings() -> None:
    assert str(connection.settings_dict["NAME"]).startswith("test_")
    executor = MigrationExecutor(connection)
    current = executor.loader.graph.leaf_nodes()
    before = [target for target in current if target[0] != "shop"] + [
        ("shop", "0004_invoice_conversation_event_relation")
    ]
    executor.migrate(before)
    completed_at = timezone.now()
    try:
        historical = executor.loader.project_state(before).apps
        old_work = historical.get_model("shop", "InboxWork")
        server = TelegramServer()
        with server.running() as address:
            owner = owner_client("before-receipt-retry")
            event_id = configured_event(owner, server, address)
            event = TelegramInbox.objects.get(pk=event_id)
            root = f"/api/v1/bots/{event.bot.id}/shop"
            original = owner.get(root).json()
            changed = owner.put(
                root,
                original["definition"]
                | {
                    "expected_revision": original["revision"],
                    "enabled": False,
                    "retry_seconds": 17,
                    "max_attempts": 1,
                },
                format="json",
            )
            assert changed.status_code == 200
            snapshot = changed.json()
            TelegramInbox.objects.filter(pk=event_id).update(processed_at=completed_at)
            prior = old_work._default_manager.create(
                event_id=event_id,
                status="failed",
                error_code="file_unavailable",
                completed_at=completed_at,
                worker_pid=12345,
            )
            work_id = prior.pk
    finally:
        MigrationExecutor(connection).migrate(current)
    connection.close()
    retained = InboxWork.objects.get(pk=work_id)
    assert retained.status == "failed" and retained.error_code == "file_unavailable"
    assert retained.worker_pid == 12345 and retained.completed_at == completed_at
    assert retained.attempts == 0 and retained.retry_at is None
    assert retained.event.processed_at == completed_at
    assert execution.begin(retained.id) is None
    assert owner.get(root).json() == snapshot
