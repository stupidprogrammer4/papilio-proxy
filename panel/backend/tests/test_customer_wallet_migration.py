"""Adding customer/wallet tables retains native queued service credentials/outbox."""

from uuid import uuid4

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from test_nodes import node_input, owner_client

from papilio_panel.modules.services.models import ServiceAccount, ServiceOutbox, XrayService

pytestmark = pytest.mark.django_db(transaction=True)


def test_customer_wallet_migration_retains_pending_service_and_encrypted_credential() -> None:
    assert str(connection.settings_dict["NAME"]).startswith("test_")
    executor = MigrationExecutor(connection)
    current = executor.loader.graph.leaf_nodes()
    before = [target for target in current if target[0] not in {"customers", "wallets"}]
    executor.migrate(before + [("customers", None)])
    try:
        owner = owner_client("before-wallets")
        node = owner.post("/api/v1/nodes", node_input("Retained node"), format="json")
        assert node.status_code == 202
        core = owner.post(
            "/api/v1/cores/xray",
            {
                "request_key": str(uuid4()),
                "node_id": node.json()["node"]["id"],
                "name": "Retained core",
            },
            format="json",
        )
        assert core.status_code == 201
        inbound = owner.post(
            f"/api/v1/cores/{core.json()['id']}/xray/inbounds",
            {
                "request_key": str(uuid4()),
                "tag": "retained",
                "public_host": "127.0.0.1",
                "port": 10888,
            },
            format="json",
        )
        assert inbound.status_code == 201
        made = owner.post(
            "/api/v1/services",
            {
                "request_key": str(uuid4()),
                "name": "Retained service",
                "core_id": core.json()["id"],
                "inbound_id": inbound.json()["id"],
            },
            format="json",
        )
        assert made.status_code == 202
        service_id = made.json()["id"]
        ciphertext = bytes(XrayService.objects.get(service_id=service_id).credential_ciphertext)
    finally:
        MigrationExecutor(connection).migrate(current)
    connection.close()
    assert ServiceAccount.objects.get(pk=service_id).name == "Retained service"
    assert ServiceAccount.objects.get(pk=service_id).status == "queued"
    assert ServiceOutbox.objects.get(service_id=service_id).dispatched_at is None
    assert bytes(XrayService.objects.get(service_id=service_id).credential_ciphertext) == ciphertext
    customer = owner.post(
        "/api/v1/customer-accounts",
        {"request_key": str(uuid4()), "name": "After migration"},
        format="json",
    )
    assert customer.status_code == 201
    wallet = owner.post(
        f"/api/v1/customer-accounts/{customer.json()['id']}/wallet",
        {"currency": "IRR", "credit_limit_minor": "0"},
        format="json",
    )
    assert wallet.status_code == 201 and wallet.json()["balance_minor"] == "0"
