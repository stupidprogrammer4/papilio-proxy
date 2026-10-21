"""Real Beat, RabbitMQ, prefork workers and independent committed reads."""

import os
import subprocess
from uuid import UUID, uuid4

import pytest
from celery.canvas import Signature
from conftest import until
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from papilio_panel.modules.jobs.domain import TaskName

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.runtime]


def logged_in() -> APIClient:
    User.objects.create_superuser(username="runtime-owner", password="long-test-password-599!")
    client = APIClient(enforce_csrf_checks=True)
    client.credentials(HTTP_X_CSRF_TOKEN=client.get("/api/v1/admin/auth/csrf").json()["csrf_token"])
    result = client.post(
        "/api/v1/admin/auth/login",
        {"username": "runtime-owner", "password": "long-test-password-599!"},
        format="json",
    )
    assert result.status_code == 200
    client.credentials(HTTP_X_CSRF_TOKEN=result.json()["csrf_token"])
    return client


def test_beat_executes_heartbeats_on_both_real_worker_queues(runtime: None) -> None:
    client = logged_in()
    until(lambda: client.get("/health/ready").status_code == 200)
    result = client.get("/api/v1/system/status").json()
    assert {worker["role"] for worker in result["workers"]} == {"io", "cpu"}
    assert all(worker["worker_pid"] != os.getpid() for worker in result["workers"])
    assert len({worker["worker_pid"] for worker in result["workers"]}) == 2


def test_outbox_runs_io_and_cpu_and_replay_does_not_execute_again(runtime: None) -> None:
    client = logged_in()
    for kind in ["io", "cpu"]:
        submitted = client.post(
            "/api/v1/system/probes", {"kind": kind, "request_key": str(uuid4())}, format="json"
        )
        assert submitted.status_code == 202
        operation = submitted.json()
        until(lambda url=operation["status_url"]: client.get(url).json()["status"] == "succeeded")
        result = client.get(operation["status_url"]).json()
        assert result["attempts"] == 1
        assert result["result"]["worker_pid"] != os.getpid()
        if kind == "io":
            assert result["result"]["database_ok"] and result["result"]["cache_ok"]
        else:
            assert len(result["result"]["digest"]) == 64
        task = TaskName.IO_PROBE if kind == "io" else TaskName.CPU_PROBE
        replay = Signature(task.value, kwargs={"operation_id": operation["id"]})
        replay.apply_async()
        sentinel = client.post(
            "/api/v1/system/probes", {"kind": kind, "request_key": str(uuid4())}, format="json"
        ).json()
        until(lambda url=sentinel["status_url"]: client.get(url).json()["status"] == "succeeded")
        assert client.get(operation["status_url"]).json()["attempts"] == 1


def test_broker_outage_preserves_request_and_redelivers_after_recovery(runtime: None) -> None:
    from kombu.exceptions import OperationalError

    from papilio_panel.modules.jobs.models import OutboxMessage
    from papilio_panel.modules.jobs.providers import publications

    container = os.environ.get("PAPILIO_TEST_BROKER_CONTAINER")
    if not container:
        pytest.skip("An explicit test-owned RabbitMQ container is required for fault injection.")
    client = logged_in()
    until(lambda: client.get("/health/ready").status_code == 200)
    command = ["docker", "exec", container, "rabbitmqctl"]
    subprocess.run([*command, "stop_app"], check=True, capture_output=True, timeout=20)
    try:
        values = {"kind": "io", "request_key": str(uuid4())}
        submitted = client.post("/api/v1/system/probes", values, format="json")
        assert submitted.status_code == 202
        operation = submitted.json()
        replayed = client.post("/api/v1/system/probes", values, format="json")
        assert replayed.json()["id"] == operation["id"]
        with pytest.raises(OperationalError):
            publications.dispatch()
        assert OutboxMessage.objects.get(operation_id=UUID(operation["id"])).dispatched_at is None
    finally:
        subprocess.run([*command, "start_app"], check=True, capture_output=True, timeout=20)
    until(lambda: client.get(operation["status_url"]).json()["status"] == "succeeded")
    assert client.get(operation["status_url"]).json()["attempts"] == 1
