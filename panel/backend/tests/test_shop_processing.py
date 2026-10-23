"""Native transaction and pause boundaries for one persisted shop event."""

import pytest
from telegram_server import TelegramServer
from test_nodes import owner_client
from test_shop_customers import configured_event

from papilio_panel.modules.bots.models import TelegramInbox
from papilio_panel.modules.shop.models import InboxWork, OutgoingMessage
from papilio_panel.modules.shop.providers import execution
from papilio_panel.shared.errors import ApplicationError

pytestmark = pytest.mark.django_db(transaction=True)


def test_pause_after_claim_retains_event_and_creates_no_reply() -> None:
    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        event_id = configured_event(client, server, address)
        work = InboxWork.objects.create(event_id=event_id)
        claim = execution.begin(work.id)
        assert claim is not None
        root = f"/api/v1/bots/{claim.event.bot.id}/shop"
        current = client.get(root).json()
        paused = current["definition"] | {
            "enabled": False,
            "expected_revision": current["revision"],
        }
        assert client.put(root, paused, format="json").status_code == 200
        try:
            execution.process(claim)
        except ApplicationError as error:
            execution.fail(claim, error.code, str(error))
        work.refresh_from_db()
        assert work.status == "queued"
        assert TelegramInbox.objects.get(pk=event_id).processed_at is None
        assert not OutgoingMessage.objects.exists()


@pytest.mark.parametrize("addressed", [False, True])
def test_admin_pairing_command_does_not_create_a_shop_customer(addressed: bool) -> None:
    from test_shop_purchases import execute

    from papilio_panel.modules.bots.providers import conversations, polling
    from papilio_panel.modules.shop.models import ShopCustomer

    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        initial = configured_event(client, server, address)
        bot = conversations.event(initial).bot
        command = f"/start@{bot.username}" if addressed else "/start"
        server.push(2, command + " pair_" + "A" * 32, chat_id=987654)
        polling.poll(bot.id)
        event = TelegramInbox.objects.get(bot_id=bot.id, update_id=2)
        assert "[pairing redacted]" in event.payload["message"]["text"]
        execute(InboxWork.objects.create(event=event))
        assert not ShopCustomer.objects.exists()
        assert not OutgoingMessage.objects.exists()
        event.refresh_from_db()
        assert event.processed_at is not None
