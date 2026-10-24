"""Synchronization upgrades retain prior service credentials and operator settings."""

from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from test_catalog_orders import product_input
from test_nodes import owner_client

from papilio_panel.modules.services.models import ServiceAccount, XrayService
from papilio_panel.shared.credentials import credential_cipher

pytestmark = pytest.mark.django_db(transaction=True)


def test_nonempty_upgrade_retains_private_identity_and_later_operator_choices() -> None:
    assert str(connection.settings_dict["NAME"]).startswith("test_")
    client = owner_client("before-service-sync")
    actor = User.objects.get(username="before-service-sync")
    definition = product_input(client)["definition"]
    ciphertext = credential_cipher().encrypt(str(uuid4()).encode())
    identifier, nonce = uuid4(), uuid4()
    executor = MigrationExecutor(connection)
    current = executor.loader.graph.leaf_nodes()
    before = [target for target in current if target[0] != "services"] + [
        ("services", "0001_initial")
    ]
    executor.migrate(before)
    started = timezone.now()
    try:
        apps = executor.loader.project_state(before).apps
        historical = apps.get_model("services", "ServiceAccount")
        historical.objects.create(
            id=identifier,
            owner_id=actor.pk,
            core_id=definition["core_id"],
            request_key=uuid4(),
            name="Retained service",
            status="succeeded",
            timeout_seconds=20,
            attempts=3,
            subscription_nonce=nonce,
            worker_pid=987,
            completed_at=started,
        )
        apps.get_model("services", "XrayService").objects.create(
            service_id=identifier,
            inbound_id=definition["inbound_id"],
            credential_ciphertext=ciphertext,
            credential_supplied=False,
            requested_level=None,
            level=7,
            email="retained-service",
        )
    finally:
        MigrationExecutor(connection).migrate(current)
    connection.close()
    row = ServiceAccount.objects.get(pk=identifier)
    assert row.status == "succeeded" and row.attempts == 3 and row.worker_pid == 987
    assert row.subscription_nonce == nonce and row.completed_at == started
    assert bytes(XrayService.objects.get(service_id=identifier).credential_ciphertext) == ciphertext
    assert row.sync_enabled is True and row.sync_interval_seconds == 60
    assert row.sync_revision == 1 and row.sync_generation == 1 and row.sync_attempts == 0
    assert row.sync_due_at > started and row.sync_last_completed_at is None
    url = f"/api/v1/services/{identifier}/synchronization"
    assert (
        client.put(
            url,
            {
                "enabled": False,
                "interval_seconds": 17,
                "expected_revision": "1",
            },
            format="json",
        ).status_code
        == 200
    )
    schedule = next(
        row
        for row in client.get("/api/v1/system/schedules").json()
        if row["key"] == "service-synchronization"
    )
    assert (
        client.put(
            "/api/v1/system/schedules/service-synchronization",
            {
                "enabled": False,
                "interval_seconds": 7,
                "expected_changed_at": schedule["changed_at"],
            },
            format="json",
        ).status_code
        == 200
    )
    call_command("migrate", interactive=False, verbosity=0)
    row.refresh_from_db()
    assert row.sync_enabled is False and row.sync_interval_seconds == 17 and row.sync_revision == 2
    retained = next(
        row
        for row in client.get("/api/v1/system/schedules").json()
        if row["key"] == "service-synchronization"
    )
    assert retained["enabled"] is False and retained["interval_seconds"] == 7
