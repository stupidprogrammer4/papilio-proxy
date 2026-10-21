"""Durable diagnostics remain scoped and idempotent across HTTP requests."""

from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db(transaction=True)


def logged_in_client(username: str) -> APIClient:
    User.objects.create_superuser(username=username, password="long-test-password-599!")
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/admin/auth/csrf").json()["csrf_token"]
    client.credentials(HTTP_X_CSRF_TOKEN=csrf)
    response = client.post(
        "/api/v1/admin/auth/login",
        {"username": username, "password": "long-test-password-599!"},
        format="json",
    )
    assert response.status_code == 200
    client.credentials(HTTP_X_CSRF_TOKEN=response.json()["csrf_token"])
    return client


def test_submitting_probe_is_durable_without_a_worker_and_is_idempotent() -> None:
    client = logged_in_client("owner")
    values = {"kind": "io", "request_key": str(uuid4())}
    response = client.post("/api/v1/system/probes", values, format="json")
    assert response.status_code == 202
    operation = response.json()
    assert operation["status"] == "queued"
    assert operation["kind"] == "io"
    replayed = client.post("/api/v1/system/probes", values, format="json")
    assert replayed.status_code == 202
    assert replayed.json()["id"] == operation["id"]
    assert client.get(operation["status_url"]).json()["id"] == operation["id"]


def test_request_key_cannot_be_reused_with_changed_input() -> None:
    client = logged_in_client("owner")
    key = str(uuid4())
    assert (
        client.post(
            "/api/v1/system/probes", {"kind": "io", "request_key": key}, format="json"
        ).status_code
        == 202
    )
    changed = client.post(
        "/api/v1/system/probes", {"kind": "cpu", "request_key": key}, format="json"
    )
    assert changed.status_code == 409


def test_other_admin_cannot_read_or_cancel_an_operation() -> None:
    owner = logged_in_client("owner")
    other = logged_in_client("other")
    response = owner.post(
        "/api/v1/system/probes", {"kind": "io", "request_key": str(uuid4())}, format="json"
    )
    operation = response.json()
    assert other.get(operation["status_url"]).status_code == 404
    assert other.post(operation["status_url"] + "/cancel").status_code == 404
    assert owner.get(operation["status_url"]).json()["status"] == "queued"


def test_anonymous_cannot_submit_or_read_diagnostics() -> None:
    client = APIClient()
    assert (
        client.post(
            "/api/v1/system/probes", {"kind": "io", "request_key": str(uuid4())}, format="json"
        ).status_code
        == 401
    )
    assert client.get("/api/v1/system/operations/" + str(uuid4())).status_code == 401


def test_queued_operation_can_be_cancelled_idempotently() -> None:
    client = logged_in_client("owner")
    response = client.post(
        "/api/v1/system/probes", {"kind": "cpu", "request_key": str(uuid4())}, format="json"
    )
    url = response.json()["status_url"]
    assert client.post(url + "/cancel").status_code == 200
    assert client.post(url + "/cancel").status_code == 200
    assert client.get(url).json()["status"] == "cancelled"


def test_application_rechecks_revoked_admin_permission() -> None:
    from papilio_panel.modules.jobs.domain import ProbeKind, ProbeSubmission
    from papilio_panel.modules.jobs.models import Operation
    from papilio_panel.modules.jobs.providers import jobs
    from papilio_panel.shared.errors import AuthenticationRejected

    user = User.objects.create_superuser(username="revoked", password="long-test-password-599!")
    User.objects.filter(pk=user.pk).update(is_staff=False)
    with pytest.raises(AuthenticationRejected):
        jobs.submit(ProbeSubmission(actor_id=user.pk, kind=ProbeKind.IO, request_key=uuid4()))
    assert Operation.objects.count() == 0


def test_worker_rechecks_permission_before_diagnostic_execution() -> None:
    from uuid import UUID

    from papilio_panel.modules.jobs.domain import ProbeKind
    from papilio_panel.modules.jobs.providers import probe_execution

    client = logged_in_client("owner")
    operation = client.post(
        "/api/v1/system/probes", {"kind": "cpu", "request_key": str(uuid4())}, format="json"
    ).json()
    User.objects.filter(username="owner").update(is_active=False)
    probe_execution.execute(UUID(operation["id"]), ProbeKind.CPU)
    User.objects.filter(username="owner").update(is_active=True)
    result = client.get(operation["status_url"]).json()
    assert result["status"] == "failed"
    assert result["error_code"] == "access_revoked"
    assert result["result"] is None


def test_io_task_entrypoint_cannot_execute_a_cpu_operation() -> None:
    from papilio_panel.config.celery import app
    from papilio_panel.modules.jobs.domain import TaskName

    client = logged_in_client("owner")
    operation = client.post(
        "/api/v1/system/probes", {"kind": "cpu", "request_key": str(uuid4())}, format="json"
    ).json()
    # Native task adapter + real DB; this component test does not claim broker delivery.
    task = app.tasks[TaskName.IO_PROBE.value]
    task.apply(kwargs={"operation_id": operation["id"]}, throw=True)
    result = client.get(operation["status_url"]).json()
    assert result["status"] == "queued"
    assert result["attempts"] == 0
    assert result["result"] is None
