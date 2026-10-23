"""Payment schema upgrade preserves prior funds and permits real settlement."""

from uuid import uuid4

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from test_manual_payments import decision, issue
from test_nodes import owner_client

from papilio_panel.modules.wallets.models import JournalEntry, Wallet

pytestmark = pytest.mark.django_db(transaction=True)


def test_payment_upgrade_preserves_prior_wallet_and_journal() -> None:
    assert str(connection.settings_dict["NAME"]).startswith("test_")
    executor = MigrationExecutor(connection)
    current = executor.loader.graph.leaf_nodes()
    before = [target for target in current if target[0] != "payments"]
    executor.migrate(before + [("payments", None)])
    try:
        owner = owner_client("before-payments")
        customer = owner.post(
            "/api/v1/customer-accounts",
            {
                "request_key": str(uuid4()),
                "name": "Retained payment customer",
            },
            format="json",
        ).json()
        root = f"/api/v1/customer-accounts/{customer['id']}/wallet"
        assert (
            owner.post(
                root, {"currency": "IRR", "credit_limit_minor": "75"}, format="json"
            ).status_code
            == 201
        )
        prior = owner.post(
            root + "/entries",
            {
                "request_key": str(uuid4()),
                "kind": "credit",
                "amount_minor": "123456",
                "reason": "Before manual payment schema",
            },
            format="json",
        )
        assert prior.status_code == 201
    finally:
        MigrationExecutor(connection).migrate(current)
    connection.close()
    wallet = Wallet.objects.get(customer_id=customer["id"])
    assert wallet.balance_minor == 123456 and wallet.credit_limit_minor == 75
    assert JournalEntry.objects.get(pk=prior.json()["id"]).balance_after_minor == 123456
    assert (
        owner.post(
            "/api/v1/payment-settings",
            {
                "recipient": "Retained operator",
                "destination": "TEST-ACCOUNT",
            },
            format="json",
        ).status_code
        == 201
    )
    invoice = issue(owner, customer["id"], "1000")
    accepted = owner.post(
        f"/api/v1/invoices/{invoice['id']}/decisions", decision(invoice), format="json"
    )
    assert accepted.status_code == 201
    connection.close()
    wallet.refresh_from_db()
    assert wallet.balance_minor == 124456 and wallet.credit_limit_minor == 75
    assert JournalEntry.objects.filter(wallet=wallet).count() == 2
    # Reapplying native migrations does not re-seed operator configuration.
    settings = owner.get("/api/v1/payment-settings").json()
    changed = settings["definition"] | {"enabled": False, "receipt_max_bytes": 8000}
    assert (
        owner.put(
            "/api/v1/payment-settings", {"expected_revision": "1", **changed}, format="json"
        ).status_code
        == 200
    )
    MigrationExecutor(connection).migrate(current)
    assert owner.get("/api/v1/payment-settings").json()["definition"] == changed
