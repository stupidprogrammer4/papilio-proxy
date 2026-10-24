"""Native Beat/worker restores a paid account after an actual managed core restart."""

import base64
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from celery.canvas import Signature
from conftest import until
from django.contrib.auth.models import User
from django.db import connection
from django.utils import timezone
from kombu.exceptions import OperationalError as BrokerError
from test_node_installation_runtime import PreparedNativeService
from test_node_installation_runtime import prepared_native_service as prepared_native_service
from test_node_runtime import listening, stop
from xray_client import subscription_client

from papilio_panel.modules.orders.models import Order
from papilio_panel.modules.services.models import ServiceAccount, XrayService
from papilio_panel.modules.services.providers import synchronization_publications
from papilio_panel.modules.services.synchronization_contracts import SynchronizationTaskName
from papilio_panel.modules.wallets.models import JournalEntry

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.runtime]


def test_native_synchronization_restores_paid_identity_without_financial_replay(
    prepared_native_service: PreparedNativeService, tmp_path: Path
) -> None:
    native = prepared_native_service
    client = native.client
    existing = client.get(native.service_url).json()
    product = client.post(
        "/api/v1/products",
        {
            "request_key": str(uuid4()),
            "definition": {
                "name": "Restart recovery",
                "core_id": existing["core_id"],
                "inbound_id": existing["inbound_id"],
                "currency": "IRR",
                "price_minor": "1000",
            },
        },
        format="json",
    )
    assert product.status_code == 201
    customer = client.post(
        "/api/v1/customer-accounts",
        {
            "request_key": str(uuid4()),
            "name": "Recovery buyer",
        },
        format="json",
    )
    assert customer.status_code == 201
    wallet = f"/api/v1/customer-accounts/{customer.json()['id']}/wallet"
    assert client.post(wallet, {"currency": "IRR"}, format="json").status_code == 201
    assert (
        client.post(
            wallet + "/entries",
            {
                "request_key": str(uuid4()),
                "kind": "credit",
                "amount_minor": "2500",
                "reason": "Controlled available funds",
            },
            format="json",
        ).status_code
        == 201
    )
    purchase = client.post(
        "/api/v1/orders",
        {
            "request_key": str(uuid4()),
            "customer_id": customer.json()["id"],
            "product_id": product.json()["id"],
            "expected_revision": "1",
            "service_name": "Purchased persistent identity",
        },
        format="json",
    )
    assert purchase.status_code == 201
    identifier = purchase.json()["service_id"]
    root = f"/api/v1/services/{identifier}"
    until(lambda: client.get(root).json()["status"] == "succeeded")
    link = client.get(root + "/subscription").json()["url"]
    uri = base64.b64decode(client.get(link).content).decode().strip()
    ciphertext = bytes(XrayService.objects.get(service_id=identifier).credential_ciphertext)
    entries = tuple(JournalEntry.objects.order_by("id").values_list("id", "amount_minor"))
    assert len(entries) == 2
    directory = tmp_path / "paid-client"
    directory.mkdir()
    with subscription_client(str(native.instance / "bin/xray"), directory, uri) as probe:
        assert probe.fetch() == b"papilio-actual-subscription-client"
        native.restart()
        with pytest.raises(OSError):
            probe.fetch()
        policy = client.get(root + "/synchronization")
        assert policy.status_code == 200
        changed = client.put(
            root + "/synchronization",
            {
                "enabled": True,
                "interval_seconds": 1,
                "expected_revision": policy.json()["revision"],
            },
            format="json",
        )
        assert changed.status_code == 200
        until(lambda: client.get(root + "/synchronization").json()["last_completed_at"] is not None)
        state = client.get(root + "/synchronization").json()
        assert state["error_code"] is None and state["worker_pid"] != os.getpid(), state
        assert probe.fetch() == b"papilio-actual-subscription-client"
    connection.close()
    assert Order.objects.count() == 1
    assert tuple(JournalEntry.objects.order_by("id").values_list("id", "amount_minor")) == entries
    assert client.get(wallet).json()["balance_minor"] == "1500"
    assert client.get(root + "/subscription").json()["url"] == link
    assert bytes(XrayService.objects.get(service_id=identifier).credential_ciphertext) == ciphertext
    assert ServiceAccount.objects.get(pk=identifier).attempts == 1


def check_node_fence(native: PreparedNativeService) -> None:
    root = f"/api/v1/nodes/{native.node_id}"
    check = native.client.post(
        root + "/operations",
        {
            "kind": "check_connection",
            "request_key": str(uuid4()),
        },
        format="json",
    )
    assert check.status_code == 202
    until(
        lambda: (
            native.client.get(root + f"/operations/{check.json()['id']}").json()["status"]
            == "succeeded"
        )
    )


def set_global_schedule(native: PreparedNativeService, enabled: bool) -> None:
    current = next(
        row
        for row in native.client.get("/api/v1/system/schedules").json()
        if row["key"] == "service-synchronization"
    )
    changed = native.client.put(
        "/api/v1/system/schedules/service-synchronization",
        {
            "enabled": enabled,
            "interval_seconds": 1,
            "expected_changed_at": current["changed_at"],
        },
        format="json",
    )
    assert changed.status_code == 200


@pytest.mark.timeout(100)
def test_pauses_stale_messages_broker_recovery_and_revoked_owner_at_real_boundaries(
    prepared_native_service: PreparedNativeService,
) -> None:
    container = os.environ.get("PAPILIO_TEST_BROKER_CONTAINER")
    if not container:
        pytest.skip("An explicitly test-owned broker is required for the outage boundary.")
    native = prepared_native_service
    client = native.client
    service = client.get(native.service_url).json()
    identifier = service["id"]
    url = native.service_url + "/synchronization"
    secret = bytes(XrayService.objects.get(service_id=identifier).credential_ciphertext)
    assert (
        client.put(
            url,
            {
                "enabled": False,
                "interval_seconds": 1,
                "expected_revision": "1",
            },
            format="json",
        ).status_code
        == 200
    )
    native.restart()
    Signature(
        SynchronizationTaskName.SYNCHRONIZE.value,
        kwargs={"service_id": identifier, "generation": "1"},
    ).apply_async()
    check_node_fence(native)
    assert ServiceAccount.objects.get(pk=identifier).sync_attempts == 0
    with pytest.raises(OSError):
        native.probe.fetch()
    set_global_schedule(native, False)
    enabled = client.put(
        url,
        {
            "enabled": True,
            "interval_seconds": 1,
            "expected_revision": "2",
        },
        format="json",
    )
    assert enabled.status_code == 200
    Signature(
        SynchronizationTaskName.SYNCHRONIZE.value,
        kwargs={"service_id": identifier, "generation": enabled.json()["generation"]},
    ).apply_async()
    check_node_fence(native)
    assert ServiceAccount.objects.get(pk=identifier).sync_attempts == 0
    with pytest.raises(OSError):
        native.probe.fetch()
    subprocess.run(
        ["docker", "exec", container, "rabbitmqctl", "stop_app"],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    try:
        set_global_schedule(native, True)
        assert (
            client.put(
                url,
                {
                    "enabled": True,
                    "interval_seconds": 1,
                    "expected_revision": "3",
                },
                format="json",
            ).status_code
            == 200
        )
        with pytest.raises((BrokerError, OSError)):
            synchronization_publications.dispatch()
        row = ServiceAccount.objects.get(pk=identifier)
        assert row.sync_enabled and row.sync_generation == 4 and row.sync_attempts == 0
        assert row.sync_dispatched_at is None and row.sync_due_at <= timezone.now()
    finally:
        subprocess.run(
            ["docker", "exec", container, "rabbitmqctl", "start_app"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    until(lambda: client.get(url).json()["last_completed_at"] is not None)
    state = client.get(url).json()
    assert state["error_code"] is None and state["worker_pid"] != os.getpid(), state
    assert native.probe.fetch() == b"papilio-actual-subscription-client"
    User.objects.filter(pk=service["owner_id"]).update(is_active=False)
    native.restart()
    until(lambda: ServiceAccount.objects.get(pk=identifier).sync_error_code == "access_revoked")
    with pytest.raises(OSError):
        native.probe.fetch()
    connection.close()
    assert bytes(XrayService.objects.get(service_id=identifier).credential_ciphertext) == secret
    retained = ServiceAccount.objects.get(pk=identifier)
    assert retained.status == "succeeded" and retained.attempts == 1


def test_attached_core_restart_recovers_while_the_agent_keeps_running(
    prepared_native_service: PreparedNativeService,
    tmp_path: Path,
) -> None:
    native = prepared_native_service
    stop(native.agent)
    until(lambda: not listening(native.agent_port) and not listening(native.api_port), timeout=5)
    configuration = native.instance / "credentials/agent.json"
    selected = json.loads(configuration.read_text())
    selected.pop("managed_xray")
    configuration.write_text(json.dumps(selected))
    core_command = [
        str(native.instance / "bin/xray"),
        "run",
        "-config",
        str(native.instance / "credentials/xray.json"),
    ]
    core = None
    with (tmp_path / "attached-core.log").open("w") as log:
        try:
            core = subprocess.Popen(core_command, stdout=log, stderr=subprocess.STDOUT)
            until(lambda: listening(native.api_port), timeout=5)
            native.agent = subprocess.Popen(
                native.command, stdout=native.log, stderr=subprocess.STDOUT
            )
            until(lambda: listening(native.agent_port), timeout=5)
            pid = native.agent.pid
            url = native.service_url + "/synchronization"
            assert (
                native.client.put(
                    url,
                    {
                        "enabled": True,
                        "interval_seconds": 1,
                        "expected_revision": "1",
                    },
                    format="json",
                ).status_code
                == 200
            )
            until(lambda: native.client.get(url).json()["last_completed_at"] is not None)
            assert native.probe.fetch() == b"papilio-actual-subscription-client"
            assert (
                native.client.put(
                    url,
                    {
                        "enabled": False,
                        "interval_seconds": 1,
                        "expected_revision": "2",
                    },
                    format="json",
                ).status_code
                == 200
            )
            stop(core)
            until(lambda: not listening(native.api_port), timeout=5)
            core = subprocess.Popen(core_command, stdout=log, stderr=subprocess.STDOUT)
            until(lambda: listening(native.api_port), timeout=5)
            assert native.agent.poll() is None and native.agent.pid == pid
            with pytest.raises(OSError):
                native.probe.fetch()
            resumed = native.client.put(
                url,
                {
                    "enabled": True,
                    "interval_seconds": 1,
                    "expected_revision": "3",
                },
                format="json",
            )
            assert resumed.status_code == 200
            until(
                lambda: (
                    int(native.client.get(url).json()["generation"])
                    > int(resumed.json()["generation"])
                )
            )
            assert native.client.get(url).json()["error_code"] is None
            assert native.probe.fetch() == b"papilio-actual-subscription-client"
            assert native.agent.poll() is None and native.agent.pid == pid
        finally:
            if core is not None:
                stop(core)
