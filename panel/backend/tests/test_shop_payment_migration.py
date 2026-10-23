"""Native event foreign-key upgrade preserves prior encrypted replies and financial data."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from telegram_server import TelegramServer
from test_manual_payments import decision, issue
from test_nodes import owner_client
from test_shop_payments import payment_bot

from papilio_panel.modules.bots.domain import TelegramReply
from papilio_panel.modules.payments.models import Invoice, PaymentDecisionEvent
from papilio_panel.modules.shop.infra.replies import decrypt_reply, encrypt_reply
from papilio_panel.modules.shop.models import OutgoingMessage

pytestmark = pytest.mark.django_db(transaction=True)


def test_event_relation_upgrade_preserves_prior_uuid_ciphertext_and_wallet() -> None:
    assert str(connection.settings_dict["NAME"]).startswith("test_")
    executor = MigrationExecutor(connection)
    current = executor.loader.graph.leaf_nodes()
    before = [target for target in current if target[0] != "shop"] + [
        ("shop", "0003_outgoingmessage_chat_id")
    ]
    executor.migrate(before)
    try:
        historical = executor.loader.project_state(before).apps
        old_messages = historical.get_model("shop", "OutgoingMessage")
        server = TelegramServer()
        with server.running() as address:
            owner = owner_client("before-shop-event-fk")
            bot, customer = payment_bot(owner, server, address)
            invoice = issue(owner, customer)
            approved = owner.post(
                f"/api/v1/invoices/{invoice['id']}/decisions", decision(invoice), format="json"
            )
            assert approved.status_code == 201
            event = PaymentDecisionEvent.objects.get()
            from papilio_panel.modules.bots.models import TelegramInbox

            incoming = TelegramInbox.objects.get(bot_id=bot, update_id=1)
            ciphertext = encrypt_reply(TelegramReply("Retained private reply"))
            old = old_messages._default_manager.create(
                event_id=incoming.pk,
                bot_id=bot,
                owner_id=event.decision.actor_id,
                invoice_id=invoice["id"],
                source_event_id=event.id,
                payload_ciphertext=ciphertext,
            )
            message_id = old.pk
    finally:
        MigrationExecutor(connection).migrate(current)
    connection.close()
    retained = OutgoingMessage.objects.get(pk=message_id)
    assert retained.source_event_id == event.id and retained.invoice_id == event.decision.invoice_id
    assert bytes(retained.payload_ciphertext) == ciphertext
    assert decrypt_reply(bytes(retained.payload_ciphertext)).text == "Retained private reply"
    assert retained.status == "queued" and retained.attempts == 0
    from uuid import uuid4

    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        OutgoingMessage.objects.filter(pk=retained.pk).update(source_event_id=uuid4())
    retained.refresh_from_db()
    assert retained.source_event_id == event.id
    assert Invoice.objects.get(pk=invoice["id"]).status == "settled"
    assert (
        owner.get(f"/api/v1/customer-accounts/{customer}/wallet").json()["balance_minor"] == "1000"
    )
