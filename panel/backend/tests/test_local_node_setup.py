"""Owner setup atomically records the optional bundled node and durable delivery."""

from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework.test import APIClient
from test_nodes import owner_client
from test_owner_setup import csrf_client, setup_token

from papilio_panel.modules.cores.models import Core, XrayInbound
from papilio_panel.modules.nodes.models import Node, NodeOutbox

pytestmark = pytest.mark.django_db(transaction=True)
PASSWORD = "isolated-local-owner-password-975!"


def local_definition() -> dict[str, object]:
    return {
        "node": {
            "name": "Bundled node",
            "endpoint_url": "https://local-node.papilio.internal:9443",
            "runtime": {"request_timeout_seconds": 3, "idle_timeout_seconds": 67},
        },
        "core_name": "Bundled Xray",
        "inbound_tag": "bundled-vless",
        "public_host": "vpn.example.test",
        "public_port": 18444,
        "default_user_level": 7,
        "bind_address": "0.0.0.0",
        "bind_port": 8443,
    }


def initialize_local_owner(definition: dict[str, object] | None = None) -> APIClient:
    client = csrf_client()
    response = client.post(
        "/api/v1/setup/owner",
        {
            "token": setup_token(),
            "username": "bundled-owner",
            "password": PASSWORD,
            "local_node": {
                "enabled": True,
                "definition": definition if definition is not None else local_definition(),
                "delivery": {"enabled": True, "retry_interval_seconds": 2, "max_attempts": 9},
            },
        },
        format="json",
    )
    assert response.status_code == 201
    assert set(response.json()) == {"id", "username"}
    login = client.post(
        "/api/v1/admin/auth/login",
        {
            "username": "bundled-owner",
            "password": PASSWORD,
        },
        format="json",
    )
    assert login.status_code == 200
    client.credentials(HTTP_X_CSRF_TOKEN=login.json()["csrf_token"])
    return client


@override_settings(PAPILIO_LOCAL_NODE_AVAILABLE=True)
def test_owner_setup_records_typed_local_metadata_without_inline_issuance() -> None:
    defaults = csrf_client().get("/api/v1/setup/local-node")
    assert defaults.status_code == 200 and defaults.json()["available"] is True
    client = initialize_local_owner()
    response = client.get("/api/v1/system/local-node")
    assert response.status_code == 200
    record = response.json()
    assert record["definition"]["node"]["runtime"]["idle_timeout_seconds"] == 67
    assert record["definition"]["default_user_level"] == 7
    assert record["delivery"] == {
        "enabled": True,
        "retry_interval_seconds": 2,
        "max_attempts": 9,
        "revision": "1",
    }
    assert record["operation"]["status"] == "queued"
    assert record["operation"]["attempts"] == "0" and record["operation"]["worker_pid"] is None
    assert Node.objects.count() == Core.objects.count() == XrayInbound.objects.count() == 1
    node = client.get(f"/api/v1/nodes/{record['node_id']}").json()
    assert node["credentials_ready"] is False
    assert NodeOutbox.objects.count() == 1
    encoded = response.content.decode()
    assert "server.key" not in encoded and "private_keys" not in encoded


@override_settings(PAPILIO_LOCAL_NODE_AVAILABLE=True)
def test_invalid_local_definition_rolls_back_owner_grant_and_all_related_records() -> None:
    from papilio_panel.modules.identity.models import OwnerSetupState, SetupGrant

    token, client = setup_token(), csrf_client()
    values = {
        "token": token,
        "username": "bundled-owner",
        "password": PASSWORD,
        "local_node": {
            "enabled": True,
            "definition": local_definition() | {"inbound_tag": "management"},
        },
    }
    response = client.post("/api/v1/setup/owner", values, format="json")
    assert response.status_code == 400
    assert User.objects.count() == Node.objects.count() == Core.objects.count() == 0
    assert not OwnerSetupState.objects.get(pk=1).claimed
    assert SetupGrant.objects.filter(consumed_at__isnull=False).count() == 0
    values["local_node"] = {"enabled": True, "definition": local_definition()}
    assert client.post("/api/v1/setup/owner", values, format="json").status_code == 201


@override_settings(PAPILIO_LOCAL_NODE_AVAILABLE=True)
def test_local_delivery_policy_is_scoped_and_revisioned_without_recreating_nodes() -> None:
    client = initialize_local_owner()
    root = "/api/v1/system/local-node"
    before = client.get(root).json()
    changed = client.put(
        root + "/delivery",
        {
            "enabled": False,
            "retry_interval_seconds": 7,
            "max_attempts": 11,
            "expected_revision": "1",
            "owner_id": 999999,
            "node_id": str(uuid4()),
        },
        format="json",
    )
    assert changed.status_code == 200
    assert changed.json()["revision"] == "2" and changed.json()["enabled"] is False
    assert (
        client.put(
            root + "/delivery",
            {
                "enabled": True,
                "retry_interval_seconds": 1,
                "max_attempts": 5,
                "expected_revision": "1",
            },
            format="json",
        ).status_code
        == 409
    )
    after = client.get(root).json()
    assert after["node_id"] == before["node_id"] and after["definition"] == before["definition"]
    assert owner_client("foreign-local-owner").get(root).status_code == 404
    assert owner_client("local-staff", superuser=False).get(root).status_code == 401
    assert APIClient().get(root).status_code == 401
    foreign = owner_client("foreign-local-write-owner")
    assert (
        foreign.put(
            root + "/delivery",
            {
                "enabled": True,
                "retry_interval_seconds": 1,
                "max_attempts": 5,
                "expected_revision": "2",
            },
            format="json",
        ).status_code
        == 404
    )
    assert (
        foreign.post(root + "/operations", {"request_key": str(uuid4())}, format="json").status_code
        == 404
    )
    assert foreign.get(root + f"/operations/{before['operation']['id']}").status_code == 404
    assert client.get(root).json() == after


@override_settings(PAPILIO_LOCAL_NODE_AVAILABLE=True)
def test_explicit_opt_out_preserves_owner_only_setup() -> None:
    response = csrf_client().post(
        "/api/v1/setup/owner",
        {
            "token": setup_token(),
            "username": "owner-only",
            "password": PASSWORD,
            "local_node": {"enabled": False},
        },
        format="json",
    )
    assert response.status_code == 201
    assert Node.objects.count() == Core.objects.count() == 0


@override_settings(PAPILIO_LOCAL_NODE_AVAILABLE=True)
def test_registration_replay_preserves_edited_delivery_and_conflicting_choices_roll_back() -> None:
    client = owner_client("local-replay-owner")
    root = "/api/v1/system/local-node"
    supplied = {"request_key": str(uuid4()), "definition": local_definition()}
    creation = client.post(root, supplied, format="json")
    assert creation.status_code == 201
    identifier = creation.json()["node_id"]
    assert (
        client.put(
            root + "/delivery",
            {
                "enabled": False,
                "retry_interval_seconds": 19,
                "max_attempts": 6,
                "expected_revision": "1",
            },
            format="json",
        ).status_code
        == 200
    )
    replay = client.post(root, supplied, format="json")
    assert replay.status_code == 200 and replay.json()["node_id"] == identifier
    assert replay.json()["delivery"]["retry_interval_seconds"] == 19
    assert replay.json()["delivery"]["enabled"] is False
    assert (
        client.post(root, supplied | {"request_key": str(uuid4())}, format="json").status_code
        == 409
    )
    foreign = owner_client("foreign-registration-owner")
    assert (
        foreign.post(root, supplied | {"request_key": str(uuid4())}, format="json").status_code
        == 404
    )
    assert Node.objects.count() == Core.objects.count() == NodeOutbox.objects.count() == 1
    for values in (
        {"enabled": True, "retry_interval_seconds": 0, "max_attempts": 5, "expected_revision": "2"},
        {
            "enabled": True,
            "retry_interval_seconds": 1,
            "max_attempts": 2147483648,
            "expected_revision": "2",
        },
        {
            "enabled": True,
            "retry_interval_seconds": 1,
            "max_attempts": 5,
            "expected_revision": "9223372036854775807",
        },
    ):
        assert client.put(root + "/delivery", values, format="json").status_code == 400
    assert client.get(root).json()["delivery"] == replay.json()["delivery"]
