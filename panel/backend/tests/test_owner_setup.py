"""Owner setup and CSRF contracts through the real HTTP/DB path."""

from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db(transaction=True)


def csrf_client() -> APIClient:
    client = APIClient(enforce_csrf_checks=True)
    response = client.get("/api/v1/admin/auth/csrf")
    assert response.status_code == 200
    client.credentials(HTTP_X_CSRF_TOKEN=response.json()["csrf_token"])
    return client


def setup_token() -> str:
    output = StringIO()
    call_command("owner_setup_token", stdout=output)
    return output.getvalue().strip()


def test_owner_setup_consumes_grant_and_closes_setup() -> None:
    token = setup_token()
    client = csrf_client()
    response = client.post(
        "/api/v1/setup/owner",
        {"token": token, "username": "owner", "password": "a-long-owner-password-749!"},
        format="json",
    )
    assert response.status_code == 201
    owner = User.objects.get(username="owner")
    assert owner.is_superuser and owner.is_staff
    assert owner.check_password("a-long-owner-password-749!")
    repeated = client.post(
        "/api/v1/setup/owner",
        {"token": token, "username": "another", "password": "another-long-password-499!"},
        format="json",
    )
    assert repeated.status_code == 409
    assert not User.objects.filter(username="another").exists()


def test_invalid_grant_does_not_create_an_account() -> None:
    setup_token()
    response = csrf_client().post(
        "/api/v1/setup/owner",
        {"token": "invalid", "username": "attacker", "password": "a-long-password-749!"},
        format="json",
    )
    assert response.status_code == 400
    assert not User.objects.filter(username="attacker").exists()


def test_setup_rejects_missing_csrf() -> None:
    response = APIClient(enforce_csrf_checks=True).post(
        "/api/v1/setup/owner",
        {"token": setup_token(), "username": "owner", "password": "a-long-password-749!"},
        format="json",
    )
    assert response.status_code == 403
    assert User.objects.count() == 0


def test_login_logout_and_anonymous_access() -> None:
    User.objects.create_superuser(username="owner", password="long-test-password-599!")
    client = csrf_client()
    assert client.get("/api/v1/admin/auth/me").status_code == 401
    response = client.post(
        "/api/v1/admin/auth/login",
        {"username": "owner", "password": "long-test-password-599!"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["username"] == "owner"
    client.credentials(HTTP_X_CSRF_TOKEN=response.json()["csrf_token"])
    assert client.get("/api/v1/admin/auth/me").status_code == 200
    assert client.post("/api/v1/admin/auth/logout").status_code == 204
    assert client.get("/api/v1/admin/auth/me").status_code == 401


def test_customer_account_read_scope_is_owner_only() -> None:
    owner = User.objects.create_superuser(username="owner", password="long-test-password-599!")
    staff = User.objects.create_user(
        username="staff", password="long-test-password-599!", is_staff=True
    )
    owner_client = APIClient()
    staff_client = APIClient()
    assert owner_client.login(username=owner.username, password="long-test-password-599!")
    assert staff_client.login(username=staff.username, password="long-test-password-599!")

    owner_scopes = owner_client.get("/api/v1/admin/auth/me").json()["scopes"]
    staff_scopes = staff_client.get("/api/v1/admin/auth/me").json()["scopes"]

    assert "customers:read" in owner_scopes
    assert "customers:write" not in owner_scopes
    assert "customers:read" not in staff_scopes


def test_login_rejects_missing_csrf_and_bad_password() -> None:
    User.objects.create_superuser(username="owner", password="long-test-password-599!")
    body = {"username": "owner", "password": "incorrect"}
    assert (
        APIClient(enforce_csrf_checks=True)
        .post("/api/v1/admin/auth/login", body, format="json")
        .status_code
        == 403
    )
    assert csrf_client().post("/api/v1/admin/auth/login", body, format="json").status_code == 401


def test_non_staff_account_cannot_enter_admin_panel() -> None:
    User.objects.create_user(username="customer", password="long-test-password-599!")
    response = csrf_client().post(
        "/api/v1/admin/auth/login",
        {"username": "customer", "password": "long-test-password-599!"},
        format="json",
    )
    assert response.status_code == 401


def test_expired_grant_does_not_close_setup_or_create_an_owner() -> None:
    from papilio_panel.modules.identity.models import OwnerSetupState, SetupGrant

    token = setup_token()
    SetupGrant.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    response = csrf_client().post(
        "/api/v1/setup/owner",
        {"token": token, "username": "owner", "password": "a-long-owner-password-749!"},
        format="json",
    )
    assert response.status_code == 400
    assert not OwnerSetupState.objects.get(pk=1).claimed
    assert User.objects.count() == 0


def test_weak_password_does_not_consume_a_valid_grant() -> None:
    from papilio_panel.modules.identity.models import SetupGrant

    token = setup_token()
    response = csrf_client().post(
        "/api/v1/setup/owner",
        {"token": token, "username": "owner", "password": "123"},
        format="json",
    )
    assert response.status_code == 400
    assert SetupGrant.objects.filter(consumed_at__isnull=False).count() == 0
    assert User.objects.count() == 0


def test_direct_setup_capability_uses_native_password_validation() -> None:
    from papilio_panel.modules.identity.domain import OwnerSetupInput
    from papilio_panel.modules.identity.providers import owner_setup
    from papilio_panel.shared.errors import InvalidInput

    token = setup_token()
    with pytest.raises(InvalidInput):
        owner_setup.complete(OwnerSetupInput(token=token, username="owner", password="123"))
    assert User.objects.count() == 0


def test_concurrent_setup_creates_exactly_one_owner() -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections

    from papilio_panel.modules.identity.domain import OwnerSetupInput
    from papilio_panel.modules.identity.providers import owner_setup
    from papilio_panel.shared.errors import Conflict

    tokens = (setup_token(), setup_token())
    barrier = Barrier(2, timeout=10)

    def initialize(values: OwnerSetupInput) -> bool:
        close_old_connections()
        try:
            barrier.wait()
            owner_setup.complete(values)
            success = True
        except Conflict:
            success = False
        finally:
            close_old_connections()
        return success

    inputs = tuple(
        OwnerSetupInput(token=token, username=f"owner-{index}", password="long-test-password-599!")
        for index, token in enumerate(tokens)
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(initialize, inputs))
    assert sorted(results) == [False, True]
    assert User.objects.filter(is_superuser=True).count() == 1
