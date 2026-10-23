"""Native private Telegram registration shares customer/wallet owners across bots."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

import pytest
from django.db import close_old_connections
from rest_framework.test import APIClient
from telegram_server import TelegramServer
from test_bots import TEST_TOKEN, bot_input
from test_nodes import owner_client

from papilio_panel.modules.bots.models import TelegramInbox
from papilio_panel.modules.bots.providers import polling
from papilio_panel.modules.customers.models import CustomerAccount
from papilio_panel.modules.shop.models import ShopCustomer
from papilio_panel.modules.shop.providers import shop_customers
from papilio_panel.modules.wallets.models import Wallet
from papilio_panel.shared.errors import Missing

pytestmark = pytest.mark.django_db(transaction=True)


def configured_event(
    client: APIClient,
    server: TelegramServer,
    address: str,
    update_id: int = 1,
    token: str = TEST_TOKEN,
) -> int:
    created = client.post(
        "/api/v1/bots",
        bot_input() | {"token": token, "runtime": {"api_base_url": address}},
        format="json",
    )
    assert created.status_code == 202
    bot_id = created.json()["id"]
    definition = client.get("/api/v1/bot-shop-defaults").json() | {
        "enabled": True,
        "public_origin": "http://panel.example.invalid",
    }
    assert client.post(f"/api/v1/bots/{bot_id}/shop", definition, format="json").status_code == 201
    server.push(update_id, "/start", chat_id=987654)
    polling.poll(UUID(bot_id))
    return TelegramInbox.objects.get(bot_id=bot_id, update_id=update_id).pk


def test_registration_preserves_existing_wallet_policy_and_shared_operator_identity() -> None:
    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        event_id = configured_event(client, server, address)
        first = shop_customers.register(event_id)
        path = f"/api/v1/customer-accounts/{first.customer.id}/wallet"
        changed = client.put(
            path, {"expected_revision": "1", "credit_limit_minor": "75"}, format="json"
        )
        assert changed.status_code == 200
        second_event = configured_event(
            client,
            server,
            address,
            update_id=2,
            token="987654321:placeholder-not-a-real-telegram-token",
        )
        second = shop_customers.register(second_event)
        assert second.customer.id == first.customer.id
        assert client.get(path).json()["credit_limit_minor"] == "75"
        assert ShopCustomer.objects.count() == 1
        assert CustomerAccount.objects.count() == 1
        assert Wallet.objects.count() == 1


def test_concurrent_registration_is_one_customer_and_wallet() -> None:
    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        event_id = configured_event(client, server, address)
        barrier = Barrier(2)

        def register(_: int) -> UUID:
            close_old_connections()
            barrier.wait(timeout=5)
            try:
                return shop_customers.register(event_id).customer.id
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            identities = set(pool.map(register, [1, 2]))
        assert len(identities) == 1
        assert ShopCustomer.objects.count() == 1
        assert CustomerAccount.objects.count() == 1
        assert Wallet.objects.count() == 1


def test_corrupt_cross_owner_customer_binding_is_not_trusted() -> None:
    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        event_id = configured_event(client, server, address)
        first = shop_customers.register(event_id)
        other = owner_client("other-customer-owner")
        foreign = other.post(
            "/api/v1/customer-accounts",
            {"request_key": "2e120cfe-b4d4-4d4b-bd3d-bca1ea688ac0", "name": "Foreign customer"},
            format="json",
        ).json()
        ShopCustomer.objects.filter(
            owner_id=first.customer.owner_id, telegram_user_id=987654
        ).update(customer_id=foreign["id"])
        with pytest.raises(Missing):
            shop_customers.register(event_id)
        assert Wallet.objects.count() == 1
