"""Durable service creation and subscription authorization on real PostgreSQL."""

from uuid import uuid4

import pytest
from rest_framework.test import APIClient
from test_nodes import node_input, owner_client

pytestmark = pytest.mark.django_db(transaction=True)


def service_input(client: APIClient) -> dict[str, object]:
    node = client.post("/api/v1/nodes", node_input(), format="json").json()["node"]
    core = client.post(
        "/api/v1/cores/xray",
        {
            "request_key": str(uuid4()),
            "node_id": node["id"],
            "name": "Xray",
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
            "port": 10443,
        },
        format="json",
    )
    assert inbound.status_code == 201
    return {
        "request_key": str(uuid4()),
        "name": "First service",
        "core_id": core.json()["id"],
        "inbound_id": inbound.json()["id"],
    }


def test_creation_is_durable_and_replay_safe_without_issuing_a_pending_subscription() -> None:
    client = owner_client("service-owner")
    assert "services:write" in client.get("/api/v1/admin/auth/me").json()["scopes"]
    values = service_input(client)
    made = client.post("/api/v1/services", values, format="json")
    assert made.status_code == 202
    row = made.json()
    assert row["status"] == "queued"
    assert row["name"] == "First service"
    assert "credential" not in row and "subscription_key" not in row
    assert client.post("/api/v1/services", values, format="json").json() == row
    assert (
        client.post("/api/v1/services", values | {"name": "different"}, format="json").status_code
        == 409
    )
    assert client.get(f"/api/v1/services/{row['id']}/subscription").status_code == 409
    assert client.get("/api/v1/services").json()["count"] == 1
    foreign = owner_client("foreign-service-owner")
    assert foreign.get(f"/api/v1/services/{row['id']}").status_code == 404
    assert foreign.get(f"/api/v1/services/{row['id']}/subscription").status_code == 404
    assert foreign.get("/api/v1/services").json()["count"] == 0
    assert (
        foreign.post(
            "/api/v1/services", values | {"request_key": str(uuid4())}, format="json"
        ).status_code
        == 404
    )


def test_inbound_must_belong_to_the_selected_core() -> None:
    client = owner_client("service-parent-owner")
    first = service_input(client)
    second = service_input(client)
    assert (
        client.post(
            "/api/v1/services", first | {"inbound_id": second["inbound_id"]}, format="json"
        ).status_code
        == 404
    )
    assert client.get("/api/v1/services").json()["count"] == 0


def test_invalid_public_subscription_does_not_disclose_an_account() -> None:
    anonymous = APIClient()
    result = anonymous.get("/api/v1/subscriptions", {"token": "not-a-valid-grant"})
    assert result.status_code == 404
    assert result.json()["code"] == "not_found"


def test_protected_fields_and_missing_csrf_cannot_bypass_provisioning() -> None:
    from django.contrib.auth.models import User

    from papilio_panel.modules.services.models import ServiceAccount

    client = owner_client("protected-service-owner")
    values = service_input(client)
    nonce = uuid4()
    made = client.post(
        "/api/v1/services",
        values
        | {
            "owner_id": 999999,
            "status": "succeeded",
            "attempts": 99,
            "subscription_nonce": str(nonce),
        },
        format="json",
    )
    assert made.status_code == 202
    row = ServiceAccount.objects.get(pk=made.json()["id"])
    assert row.owner_id == User.objects.get(username="protected-service-owner").pk
    assert row.status == "queued" and row.attempts == 0
    assert row.subscription_nonce != nonce
    client.credentials()
    result = client.post("/api/v1/services", values | {"request_key": str(uuid4())}, format="json")
    assert result.status_code == 403
    assert ServiceAccount.objects.count() == 1
