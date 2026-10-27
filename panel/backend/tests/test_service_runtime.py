"""Actual service API/outbox/Beat/worker/agent/core and subscription client boundary."""

import base64
import os
import subprocess
import urllib.error
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

import pytest
from celery.canvas import Signature
from conftest import until
from django.contrib.auth.models import User
from django.db import connection
from django.utils import timezone
from kombu.exceptions import OperationalError
from rest_framework.test import APIClient
from test_node_user_control import native_control as native_control
from test_nodes import owner_client
from xray_client import subscription_client

from papilio_panel.modules.cores.models import XrayCore
from papilio_panel.modules.nodes.domain import XrayApply
from papilio_panel.modules.nodes.providers import xray_control
from papilio_panel.modules.services.domain import ServiceTaskName
from papilio_panel.modules.services.infra.schedules import initialize_services
from papilio_panel.modules.services.models import ServiceAccount, ServiceOutbox, XrayService
from papilio_panel.modules.services.providers import publications

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.runtime]


def existing_owner_client() -> APIClient:
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/admin/auth/csrf").json()["csrf_token"]
    client.credentials(HTTP_X_CSRF_TOKEN=csrf)
    response = client.post(
        "/api/v1/admin/auth/login",
        {
            "username": "native-user-owner",
            "password": "isolated-node-owner-password-944!",
        },
        format="json",
    )
    assert response.status_code == 200
    client.credentials(HTTP_X_CSRF_TOKEN=response.json()["csrf_token"])
    return client


def test_node_traffic_operation_reads_native_user_counters(
    native_control: tuple[XrayApply, int, str], tmp_path: Path
) -> None:
    node, data_port, binary = native_control
    client = existing_owner_client()
    applied = xray_control.apply(node)
    assert applied.succeeded
    uri = (
        f"vless://{node.user.identifier}@127.0.0.1:{data_port}"
        f"?encryption=none&type=tcp&security=none#{node.user.identity.email}"
    )
    with subscription_client(binary, tmp_path, uri) as probe:
        assert probe.fetch() == b"papilio-actual-subscription-client"

    root = f"/api/v1/nodes/{node.node_id}/operations"
    submitted = client.post(
        root,
        {"request_key": str(uuid4()), "kind": "read_traffic"},
        format="json",
    )
    assert submitted.status_code == 202
    operation_id = submitted.json()["id"]
    operation_url = f"{root}/{operation_id}"
    until(lambda: client.get(operation_url).json()["status"] in {"succeeded", "failed"})
    result = client.get(operation_url).json()
    assert result["status"] == "succeeded"
    assert result["traffic"]["uptime_seconds"] > 0
    counters = result["traffic"]["counters"]
    user_counters = [item for item in counters if item["email"] == node.user.identity.email]
    assert {item["direction"] for item in user_counters} == {"uplink", "downlink"}, result
    assert all(item["bytes"] > 0 for item in user_counters)
    unrelated_owner = owner_client("unrelated-traffic-reader")
    assert unrelated_owner.get(operation_url).status_code == 404


def test_real_service_provisioning_and_public_subscription_connect_a_native_client(
    native_control: tuple[XrayApply, int, str],
    tmp_path: Path,
) -> None:
    node, data_port, binary = native_control
    client = existing_owner_client()
    core = client.post(
        "/api/v1/cores/xray",
        {
            "request_key": str(uuid4()),
            "node_id": str(node.node_id),
            "name": "Real attached Xray",
            "default_user_level": 7,
        },
        format="json",
    )
    assert core.status_code == 201
    inbound = client.post(
        f"/api/v1/cores/{core.json()['id']}/xray/inbounds",
        {
            "request_key": str(uuid4()),
            "tag": "vless-test",
            "public_host": "127.0.0.1",
            "port": data_port,
        },
        format="json",
    )
    assert inbound.status_code == 201
    identifier = uuid4()
    values = {
        "request_key": str(uuid4()),
        "name": "سرویس واقعی",
        "core_id": core.json()["id"],
        "inbound_id": inbound.json()["id"],
        "identifier": str(identifier),
    }
    made = client.post("/api/v1/services", values, format="json")
    assert made.status_code == 202
    root = f"/api/v1/services/{made.json()['id']}"
    until(lambda: client.get(root).json()["status"] in {"succeeded", "failed"})
    outcome = client.get(root).json()
    assert outcome["status"] == "succeeded", outcome
    assert outcome["worker_pid"] != os.getpid()
    assert outcome["attempts"] == 1
    connection.close()
    account = ServiceAccount.objects.get(pk=made.json()["id"])
    credential = XrayService.objects.get(service_id=account.id)
    assert str(identifier).encode() not in bytes(credential.credential_ciphertext)
    assert credential.level == 7
    assert ServiceOutbox.objects.get(service=account).dispatched_at is not None
    link = client.get(root + "/subscription")
    assert link.status_code == 200 and link["Cache-Control"] == "private, no-store"
    url = link.json()["url"]
    anonymous = APIClient()
    response = anonymous.get(url)
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    uri = base64.b64decode(response.content).decode().strip()
    parsed = urlsplit(uri)
    assert parsed.username == str(identifier)
    assert parsed.hostname == "127.0.0.1" and parsed.port == data_port
    assert unquote(parsed.fragment) == values["name"]
    assert parse_qs(parsed.query) == {"encryption": ["none"], "type": ["tcp"], "security": ["none"]}
    with subscription_client(binary, tmp_path, uri) as probe:
        assert probe.fetch() == b"papilio-actual-subscription-client"
    XrayCore.objects.filter(core_id=account.core_id).update(default_user_level=9)
    replay = client.post("/api/v1/services", values, format="json")
    assert replay.status_code == 202 and replay.json()["id"] == str(account.id)
    credential.refresh_from_db()
    assert credential.level == 7
    Signature(ServiceTaskName.PROVISION.value, kwargs={"service_id": str(account.id)}).apply_async()
    sentinel = client.post(
        "/api/v1/services",
        values
        | {"request_key": str(uuid4()), "name": "Queue sentinel", "identifier": str(uuid4())},
        format="json",
    )
    assert sentinel.status_code == 202
    until(
        lambda: (
            client.get(f"/api/v1/services/{sentinel.json()['id']}").json()["status"] == "succeeded"
        )
    )
    account.refresh_from_db()
    assert account.attempts == 1
    encrypted = bytes(credential.credential_ciphertext)
    ServiceAccount.objects.filter(pk=account.id).update(
        status="running",
        lease_token=uuid4(),
        lease_until=timezone.now() - timedelta(seconds=1),
    )
    ServiceOutbox.objects.filter(service=account).update(dispatched_at=None)
    until(lambda: client.get(root).json()["status"] == "succeeded")
    account.refresh_from_db()
    credential.refresh_from_db()
    assert account.attempts == 2
    assert bytes(credential.credential_ciphertext) == encrypted
    assert client.get(root + "/subscription").json()["url"] == url
    with subscription_client(binary, tmp_path, uri) as probe:
        assert probe.fetch() == b"papilio-actual-subscription-client"
    User.objects.filter(pk=node.actor_id).update(is_active=False)
    assert anonymous.get(url).status_code == 404
    User.objects.filter(pk=node.actor_id).update(is_active=True)
    assert anonymous.get(url).status_code == 200
    ServiceAccount.objects.filter(pk=account.id).update(subscription_nonce=uuid4())
    assert anonymous.get(url).status_code == 404


def test_paused_delivery_and_broker_outage_preserve_requests_until_real_recovery(
    native_control: tuple[XrayApply, int, str],
    tmp_path: Path,
) -> None:
    container = os.environ.get("PAPILIO_TEST_BROKER_CONTAINER")
    if not container:
        pytest.skip("An explicitly test-owned broker is required for native fault injection.")
    node, data_port, binary = native_control
    client = existing_owner_client()
    core = client.post(
        "/api/v1/cores/xray",
        {"request_key": str(uuid4()), "node_id": str(node.node_id), "name": "Recovery core"},
        format="json",
    )
    assert core.status_code == 201
    inbound = client.post(
        f"/api/v1/cores/{core.json()['id']}/xray/inbounds",
        {
            "request_key": str(uuid4()),
            "tag": "vless-test",
            "public_host": "127.0.0.1",
            "port": data_port,
        },
        format="json",
    )
    assert inbound.status_code == 201
    schedule_url = "/api/v1/system/schedules/service-outbox"
    schedule = next(
        row
        for row in client.get("/api/v1/system/schedules").json()
        if row["key"] == "service-outbox"
    )
    paused = client.put(
        schedule_url,
        {"enabled": False, "interval_seconds": 2, "expected_changed_at": schedule["changed_at"]},
        format="json",
    )
    assert paused.status_code == 200
    initialize_services(sender=object())
    retained = next(
        row
        for row in client.get("/api/v1/system/schedules").json()
        if row["key"] == "service-outbox"
    )
    assert retained["enabled"] is False and retained["interval_seconds"] == 2
    values = {
        "request_key": str(uuid4()),
        "name": "Paused service",
        "core_id": core.json()["id"],
        "inbound_id": inbound.json()["id"],
    }
    first = client.post("/api/v1/services", values, format="json")
    assert first.status_code == 202
    publications.dispatch()
    # A real worker barrier proves the runtime still operates while service delivery pauses.
    probe = client.post(
        "/api/v1/system/probes", {"kind": "io", "request_key": str(uuid4())}, format="json"
    )
    assert probe.status_code == 202
    until(
        lambda: (
            client.get(f"/api/v1/system/operations/{probe.json()['id']}").json()["status"]
            == "succeeded"
        )
    )
    row = ServiceAccount.objects.get(pk=first.json()["id"])
    assert row.status == "queued" and row.attempts == 0
    assert ServiceOutbox.objects.get(service=row).dispatched_at is None
    command = ["docker", "exec", container, "rabbitmqctl"]
    subprocess.run([*command, "stop_app"], check=True, capture_output=True, timeout=20)
    try:
        enabled = client.put(
            schedule_url,
            {"enabled": True, "interval_seconds": 2, "expected_changed_at": retained["changed_at"]},
            format="json",
        )
        assert enabled.status_code == 200
        second = client.post(
            "/api/v1/services",
            values | {"request_key": str(uuid4()), "name": "Offline broker service"},
            format="json",
        )
        assert second.status_code == 202
        assert (
            client.post("/api/v1/services", values, format="json").json()["id"]
            == first.json()["id"]
        )
        with pytest.raises(OperationalError):
            publications.dispatch()
        assert ServiceOutbox.objects.filter(dispatched_at__isnull=True).count() == 2
    finally:
        subprocess.run([*command, "start_app"], check=True, capture_output=True, timeout=20)
    until(lambda: ServiceAccount.objects.filter(status="succeeded").count() == 2)
    connection.close()
    assert set(ServiceAccount.objects.values_list("attempts", flat=True)) == {1}
    assert ServiceAccount.objects.count() == 2
    link = client.get(f"/api/v1/services/{second.json()['id']}/subscription")
    assert link.status_code == 200
    response = APIClient().get(link.json()["url"])
    assert response.status_code == 200
    uri = base64.b64decode(response.content).decode().strip()
    with subscription_client(binary, tmp_path, uri) as tunnel:
        assert tunnel.fetch() == b"papilio-actual-subscription-client"


def test_revoked_actor_cannot_provision_an_already_accepted_service(
    native_control: tuple[XrayApply, int, str],
    tmp_path: Path,
) -> None:
    node, data_port, binary = native_control
    client = existing_owner_client()
    core = client.post(
        "/api/v1/cores/xray",
        {"request_key": str(uuid4()), "node_id": str(node.node_id), "name": "Revocation core"},
        format="json",
    )
    assert core.status_code == 201
    inbound = client.post(
        f"/api/v1/cores/{core.json()['id']}/xray/inbounds",
        {
            "request_key": str(uuid4()),
            "tag": "vless-test",
            "public_host": "127.0.0.1",
            "port": data_port,
        },
        format="json",
    )
    assert inbound.status_code == 201
    schedule = next(
        row
        for row in client.get("/api/v1/system/schedules").json()
        if row["key"] == "service-outbox"
    )
    paused = client.put(
        "/api/v1/system/schedules/service-outbox",
        {
            "enabled": False,
            "interval_seconds": 1,
            "expected_changed_at": schedule["changed_at"],
        },
        format="json",
    )
    assert paused.status_code == 200
    identifier = uuid4()
    made = client.post(
        "/api/v1/services",
        {
            "request_key": str(uuid4()),
            "name": "Revoked request",
            "core_id": core.json()["id"],
            "inbound_id": inbound.json()["id"],
            "identifier": str(identifier),
        },
        format="json",
    )
    assert made.status_code == 202
    User.objects.filter(pk=node.actor_id).update(is_active=False)
    operator = owner_client("other-runtime-owner")
    resumed = operator.put(
        "/api/v1/system/schedules/service-outbox",
        {
            "enabled": True,
            "interval_seconds": 1,
            "expected_changed_at": paused.json()["changed_at"],
        },
        format="json",
    )
    assert resumed.status_code == 200
    until(lambda: ServiceAccount.objects.get(pk=made.json()["id"]).status == "failed")
    row = ServiceAccount.objects.get(pk=made.json()["id"])
    assert row.error_code == "access_revoked" and row.worker_pid != os.getpid()
    uri = f"vless://{identifier}@127.0.0.1:{data_port}?encryption=none&type=tcp&security=none"
    with (
        subscription_client(binary, tmp_path, uri) as tunnel,
        pytest.raises((OSError, urllib.error.URLError)),
    ):
        tunnel.fetch()
