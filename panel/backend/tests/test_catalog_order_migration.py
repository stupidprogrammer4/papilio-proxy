"""New catalogue/order schema preserves existing customer funds and journal."""

from uuid import uuid4

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from test_catalog_orders import product_input
from test_nodes import owner_client

from papilio_panel.modules.wallets.models import JournalEntry, Wallet

pytestmark = pytest.mark.django_db(transaction=True)


def test_catalogue_and_orders_upgrade_keeps_old_funds_and_posts_a_real_purchase() -> None:
    assert str(connection.settings_dict["NAME"]).startswith("test_")
    executor = MigrationExecutor(connection)
    current = executor.loader.graph.leaf_nodes()
    before = [target for target in current if target[0] not in {"catalog", "orders"}]
    executor.migrate(before + [("catalog", None)])
    try:
        owner = owner_client("before-orders")
        customer = owner.post(
            "/api/v1/customer-accounts",
            {"request_key": str(uuid4()), "name": "Retained buyer"},
            format="json",
        ).json()
        path = f"/api/v1/customer-accounts/{customer['id']}/wallet"
        assert (
            owner.post(
                path, {"currency": "IRR", "credit_limit_minor": "75"}, format="json"
            ).status_code
            == 201
        )
        journal = owner.post(
            path + "/entries",
            {
                "request_key": str(uuid4()),
                "kind": "credit",
                "amount_minor": "123456",
                "reason": "Before catalogue upgrade",
            },
            format="json",
        )
        assert journal.status_code == 201
    finally:
        MigrationExecutor(connection).migrate(current)
    connection.close()
    wallet = Wallet.objects.get(customer_id=customer["id"])
    assert wallet.balance_minor == 123456 and wallet.credit_limit_minor == 75
    assert JournalEntry.objects.get(pk=journal.json()["id"]).balance_after_minor == 123456
    product = owner.post("/api/v1/products", product_input(owner), format="json")
    assert product.status_code == 201
    order = owner.post(
        "/api/v1/orders",
        {
            "request_key": str(uuid4()),
            "customer_id": customer["id"],
            "product_id": product.json()["id"],
            "expected_revision": "1",
            "service_name": "After upgrade",
        },
        format="json",
    )
    assert order.status_code == 201
    connection.close()
    wallet.refresh_from_db()
    assert wallet.balance_minor == 122456
    assert JournalEntry.objects.filter(wallet=wallet).count() == 2
