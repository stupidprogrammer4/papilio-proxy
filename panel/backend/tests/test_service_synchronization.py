"""Owner synchronization policy is scoped, versioned and independent of provisioning."""

from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from test_catalog_orders import product_input
from test_nodes import owner_client

pytestmark = pytest.mark.django_db(transaction=True)


def synchronization_context() -> tuple[APIClient, str, str]:
    client = owner_client("synchronization-owner")
    definition = product_input(client)["definition"]
    made = client.post(
        "/api/v1/services",
        {
            "request_key": str(uuid4()),
            "name": "Persisted service",
            "core_id": definition["core_id"],
            "inbound_id": definition["inbound_id"],
        },
        format="json",
    )
    assert made.status_code == 202
    root = f"/api/v1/services/{made.json()['id']}"
    return client, root + "/synchronization", made.json()["id"]


def test_owner_can_pause_and_retime_without_resetting_provisioning_or_credentials() -> None:
    from papilio_panel.modules.services.models import ServiceAccount, XrayService

    client, url, identifier = synchronization_context()
    before = client.get(f"/api/v1/services/{identifier}").json()
    secret = bytes(XrayService.objects.get(service_id=identifier).credential_ciphertext)
    response = client.get(url)
    assert response.status_code == 200
    policy = response.json()
    assert policy["enabled"] is True and policy["interval_seconds"] == 60
    assert policy["revision"] == "1" and policy["generation"] == "1"
    paused = client.put(
        url,
        {
            "enabled": False,
            "interval_seconds": 7,
            "expected_revision": policy["revision"],
            "owner_id": 999999,
            "attempts": 999,
            "error_code": "injected",
        },
        format="json",
    )
    assert paused.status_code == 200
    assert paused.json()["enabled"] is False
    assert paused.json()["interval_seconds"] == 7
    assert paused.json()["revision"] == "2" and paused.json()["generation"] == "2"
    assert (
        client.put(
            url,
            {
                "enabled": True,
                "interval_seconds": 1,
                "expected_revision": "1",
            },
            format="json",
        ).status_code
        == 409
    )
    assert client.get(f"/api/v1/services/{identifier}").json() == before
    row = ServiceAccount.objects.get(pk=identifier)
    assert row.sync_attempts == 0 and row.sync_error_code is None
    assert bytes(XrayService.objects.get(service_id=identifier).credential_ciphertext) == secret


def test_sync_policy_requires_current_owner_and_valid_native_bounds() -> None:
    client, url, identifier = synchronization_context()
    assert client.get(url).status_code == 200
    for invalid in (0, -1, 2147483648):
        assert (
            client.put(
                url,
                {
                    "enabled": True,
                    "interval_seconds": invalid,
                    "expected_revision": "1",
                },
                format="json",
            ).status_code
            == 400
        )
    assert (
        client.put(
            url,
            {
                "enabled": True,
                "interval_seconds": 1,
                "expected_revision": "9223372036854775808",
            },
            format="json",
        ).status_code
        == 400
    )
    assert owner_client("foreign-synchronization-owner").get(url).status_code == 404
    assert APIClient().get(url).status_code == 401
    assert client.get(f"/api/v1/services/{uuid4()}/synchronization").status_code == 404
    User.objects.filter(username="synchronization-owner").update(is_superuser=False)
    assert client.get(url).status_code == 401
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
        == 401
    )
