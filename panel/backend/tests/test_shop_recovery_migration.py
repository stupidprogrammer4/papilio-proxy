"""Native recovery upgrade retains prior work, ciphertext and operator choices."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from telegram_server import TelegramServer
from test_nodes import owner_client
from test_shop_customers import configured_event

from papilio_panel.modules.bots.domain import TelegramReply
from papilio_panel.modules.bots.models import TelegramInbox
from papilio_panel.modules.shop.infra.replies import encrypt_reply
from papilio_panel.modules.shop.models import (
    InboxWork,
    MessageRecovery,
    OutgoingMessage,
    WorkRecovery,
)

pytestmark = pytest.mark.django_db(transaction=True)


def test_recovery_upgrade_preserves_nonempty_queue_and_seeded_operator_choices() -> None:
    assert str(connection.settings_dict["NAME"]).startswith("test_")
    executor = MigrationExecutor(connection)
    current = executor.loader.graph.leaf_nodes()
    before = [target for target in current if target[0] != "shop"] + [
        ("shop", "0005_receipt_preparation_retries")
    ]
    executor.migrate(before)
    retry_at = timezone.now()
    try:
        historical = executor.loader.project_state(before).apps
        old_work = historical.get_model("shop", "InboxWork")
        old_messages = historical.get_model("shop", "OutgoingMessage")
        server = TelegramServer()
        with server.running() as address:
            owner = owner_client("before-owner-recovery")
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
                    "delivery_enabled": False,
                    "retry_seconds": 17,
                    "max_attempts": 9,
                },
                format="json",
            )
            assert changed.status_code == 200
            policy_snapshot = changed.json()
            prior_work = old_work._default_manager.create(
                event_id=event_id,
                status="queued",
                attempts=4,
                error_code="connection_failed",
                retry_at=retry_at,
            )
            ciphertext = encrypt_reply(TelegramReply("Retained private reply"))
            prior_message = old_messages._default_manager.create(
                event_id=event_id,
                bot_id=event.bot.id,
                owner_id=event.bot.owner_id,
                status="ambiguous",
                attempts=5,
                error_code="sender_lease_expired",
                payload_ciphertext=ciphertext,
            )
            work_id, message_id = prior_work.pk, prior_message.pk
    finally:
        MigrationExecutor(connection).migrate(current)
    connection.close()
    work = InboxWork.objects.get(pk=work_id)
    message = OutgoingMessage.objects.get(pk=message_id)
    assert work.revision == 1 and work.attempts == 4 and work.retry_at == retry_at
    assert work.status == "queued" and work.error_code == "connection_failed"
    assert message.revision == 1 and message.attempts == 5 and message.status == "ambiguous"
    assert bytes(message.payload_ciphertext) == ciphertext
    assert WorkRecovery.objects.count() == 0 and MessageRecovery.objects.count() == 0
    assert owner.get(root).json() == policy_snapshot
