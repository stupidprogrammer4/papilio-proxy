"""Private Telegram confirmations use one purchase identity across repeated taps."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from telegram_server import TelegramServer
from test_catalog_orders import product_input
from test_nodes import owner_client
from test_shop_customers import configured_event

from papilio_panel.modules.bots.models import TelegramInbox
from papilio_panel.modules.bots.providers import conversations, polling
from papilio_panel.modules.orders.models import Order
from papilio_panel.modules.services.models import ServiceAccount, ServiceOutbox
from papilio_panel.modules.shop.infra.replies import decrypt_reply
from papilio_panel.modules.shop.models import InboxWork, OutgoingMessage, PurchaseIntent
from papilio_panel.modules.shop.providers import execution, shop_customers
from papilio_panel.shared.errors import Conflict, Missing

pytestmark = pytest.mark.django_db(transaction=True)


def incoming_callback(
    server: TelegramServer, bot_id: UUID, update_id: int, command: str, sender: int = 987654
) -> InboxWork:
    original = TelegramInbox.objects.filter(bot_id=bot_id).earliest("id")
    identity = conversations.event(original.pk).bot.telegram_id
    assert identity is not None
    server.push_callback(update_id, command, chat_id=sender, bot_id=identity)
    polling.poll(bot_id)
    event = TelegramInbox.objects.get(bot_id=bot_id, update_id=update_id)
    return InboxWork.objects.create(event=event)


def execute(work: InboxWork) -> None:
    claim = execution.begin(work.id)
    assert claim is not None
    execution.process(claim)


def purchase_fixture(
    client: APIClient, server: TelegramServer, address: str
) -> tuple[UUID, dict, str]:
    event_id = configured_event(client, server, address)
    customer = shop_customers.register(event_id)
    values = product_input(client)
    response = client.post("/api/v1/products", values, format="json")
    assert response.status_code == 201
    wallet = f"/api/v1/customer-accounts/{customer.customer.id}/wallet"
    funds = client.post(
        wallet + "/entries",
        {
            "request_key": str(uuid4()),
            "kind": "credit",
            "amount_minor": "5000",
            "reason": "Controlled funds",
        },
        format="json",
    )
    assert funds.status_code == 201
    return customer.event.bot.id, response.json(), wallet


def test_repeated_taps_keep_one_order_debit_service_and_private_confirmation() -> None:
    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        bot, product, wallet = purchase_fixture(client, server, address)
        selected = incoming_callback(server, bot, 2, f"offer:{UUID(product['id']).hex}")
        execute(selected)
        confirmation = PurchaseIntent.objects.get(pk=selected.id)
        assert confirmation.offer_revision == 1
        rendered = decrypt_reply(
            bytes(OutgoingMessage.objects.get(event=selected.event).payload_ciphertext)
        )
        buy = next(button for button in rendered.buttons if button.callback_data.startswith("buy:"))
        assert "1000" in rendered.text and buy.callback_data == f"buy:{confirmation.id.hex}"
        execute(incoming_callback(server, bot, 3, buy.callback_data))
        execute(incoming_callback(server, bot, 4, buy.callback_data))
        confirmation.refresh_from_db()
        order = Order.objects.get(pk=confirmation.order_id)
        assert (
            order.customer_id == confirmation.customer_id and order.request_key == confirmation.id
        )
        assert client.get(wallet).json()["balance_minor"] == "4000"
        assert client.get(wallet + "/entries").json()["count"] == 2
        assert Order.objects.count() == 1
        assert ServiceAccount.objects.count() == 1 and ServiceOutbox.objects.count() == 1
        assert OutgoingMessage.objects.filter(event__update_id__in=[3, 4]).count() == 2
        # The same confirmation cannot be used by another customer of this owner.
        foreign = incoming_callback(server, bot, 5, buy.callback_data, sender=998877)
        claim = execution.begin(foreign.id)
        assert claim is not None
        with pytest.raises(Missing):
            execution.process(claim)
        assert Order.objects.count() == 1 and client.get(wallet).json()["balance_minor"] == "4000"
        # An already purchased confirmation can still show its original order after expiry.
        PurchaseIntent.objects.filter(pk=confirmation.id).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        execute(incoming_callback(server, bot, 6, buy.callback_data))
        assert Order.objects.count() == 1


@pytest.mark.parametrize("change", ["expired", "price", "disabled"])
def test_unpaid_expired_or_changed_offer_cannot_debit_wallet(change: str) -> None:
    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        bot, product, wallet = purchase_fixture(client, server, address)
        selected = incoming_callback(server, bot, 2, f"offer:{UUID(product['id']).hex}")
        execute(selected)
        confirmation = PurchaseIntent.objects.get(pk=selected.id)
        if change == "expired":
            PurchaseIntent.objects.filter(pk=confirmation.id).update(
                expires_at=timezone.now() - timedelta(seconds=1)
            )
        else:
            changed = client.put(
                f"/api/v1/products/{product['id']}",
                {
                    "expected_revision": "1",
                    "definition": product["offer"]["definition"]
                    | ({"price_minor": "2000"} if change == "price" else {"is_active": False}),
                },
                format="json",
            )
            assert changed.status_code == 200
        work = incoming_callback(server, bot, 3, f"buy:{confirmation.id.hex}")
        claim = execution.begin(work.id)
        assert claim is not None
        with pytest.raises(Conflict):
            execution.process(claim)
        assert Order.objects.count() == 0 and ServiceAccount.objects.count() == 0
        assert client.get(wallet).json()["balance_minor"] == "5000"
        assert not OutgoingMessage.objects.filter(event=work.event).exists()


def test_order_queries_are_customer_scoped_and_pending_has_no_subscription() -> None:
    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        bot, product, _ = purchase_fixture(client, server, address)
        selected = incoming_callback(server, bot, 2, f"offer:{UUID(product['id']).hex}")
        execute(selected)
        execute(incoming_callback(server, bot, 3, f"buy:{selected.id.hex}"))
        order = Order.objects.get()
        listing = incoming_callback(server, bot, 4, "orders:1")
        execute(listing)
        response = decrypt_reply(
            bytes(OutgoingMessage.objects.get(event=listing.event).payload_ciphertext)
        )
        assert any(button.callback_data == f"order:{order.id.hex}" for button in response.buttons)
        status = incoming_callback(server, bot, 5, f"order:{order.id.hex}")
        execute(status)
        response = decrypt_reply(
            bytes(OutgoingMessage.objects.get(event=status.event).payload_ciphertext)
        )
        assert "queued" in response.text and "?token=" not in response.text
        foreign = incoming_callback(server, bot, 6, f"order:{order.id.hex}", sender=998877)
        claim = execution.begin(foreign.id)
        assert claim is not None
        with pytest.raises(Missing):
            execution.process(claim)
        assert not OutgoingMessage.objects.filter(event=foreign.event).exists()
        foreign_list = incoming_callback(server, bot, 7, "orders:1", sender=998877)
        execute(foreign_list)
        response = decrypt_reply(
            bytes(OutgoingMessage.objects.get(event=foreign_list.event).payload_ciphertext)
        )
        assert not any(button.callback_data.startswith("order:") for button in response.buttons)


def test_concurrent_confirmation_callbacks_commit_one_financial_effect() -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections

    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        bot, product, wallet = purchase_fixture(client, server, address)
        selected = incoming_callback(server, bot, 2, f"offer:{UUID(product['id']).hex}")
        execute(selected)
        first = incoming_callback(server, bot, 3, f"buy:{selected.id.hex}")
        second = incoming_callback(server, bot, 4, f"buy:{selected.id.hex}")
        barrier = Barrier(2)

        def confirm(work: InboxWork) -> None:
            close_old_connections()
            barrier.wait(timeout=5)
            try:
                execute(work)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(confirm, [first, second]))
        assert Order.objects.count() == 1 and ServiceAccount.objects.count() == 1
        assert ServiceOutbox.objects.count() == 1
        assert client.get(wallet).json()["balance_minor"] == "4000"
        assert client.get(wallet + "/entries").json()["count"] == 2
        assert InboxWork.objects.filter(pk__in=[first.id, second.id], status="done").count() == 2


def test_invalid_render_rolls_back_purchase_debit_service_and_reply() -> None:
    from papilio_panel.shared.errors import InvalidInput

    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        bot, product, wallet = purchase_fixture(client, server, address)
        selected = incoming_callback(server, bot, 2, f"offer:{UUID(product['id']).hex}")
        execute(selected)
        path = f"/api/v1/bots/{bot}/shop"
        current = client.get(path).json()
        definition = current["definition"]
        definition["texts"]["fa"]["queued"] = "$order_id" * 120
        assert (
            client.put(
                path, definition | {"expected_revision": current["revision"]}, format="json"
            ).status_code
            == 200
        )
        work = incoming_callback(server, bot, 3, f"buy:{selected.id.hex}")
        claim = execution.begin(work.id)
        assert claim is not None
        with pytest.raises(InvalidInput):
            execution.process(claim)
        assert Order.objects.count() == 0 and ServiceAccount.objects.count() == 0
        assert ServiceOutbox.objects.count() == 0
        assert client.get(wallet).json()["balance_minor"] == "5000"
        assert client.get(wallet + "/entries").json()["count"] == 1
        assert PurchaseIntent.objects.get(pk=selected.id).order_id is None
        assert TelegramInbox.objects.get(pk=work.event_id).processed_at is None
        assert not OutgoingMessage.objects.filter(event=work.event).exists()
