"""Real Beat, RabbitMQ, prefork workers and independent committed reads."""

import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import pytest
from celery.canvas import Signature
from django.contrib.auth.models import User
from django.db import connection
from django_celery_beat.models import IntervalSchedule, PeriodicTask
from rest_framework.test import APIClient

from papilio_panel.config.celery import app
from papilio_panel.modules.jobs.domain import TaskName

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.runtime]
BACKEND = Path(__file__).resolve().parents[1]


def until(predicate: Callable[[], bool], timeout: float = 35) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        connection.close()
        if predicate():
            return
        time.sleep(0.1)
    pytest.fail("The bounded runtime completion condition was not reached.")


@pytest.fixture
def runtime(tmp_path: Path) -> Iterator[None]:
    database_name = str(connection.settings_dict["NAME"])
    assert database_name.startswith("test_"), "Only a test-owned database may run this fixture."
    env = os.environ.copy()
    parsed = urlsplit(env["DATABASE_URL"])
    env["DATABASE_URL"] = urlunsplit(parsed._replace(path="/" + database_name))
    env["DJANGO_SETTINGS_MODULE"] = "papilio_panel.config.settings"
    interval, _ = IntervalSchedule.objects.get_or_create(every=1, period=IntervalSchedule.SECONDS)
    for task in PeriodicTask.objects.filter(task__startswith="papilio."):
        task.interval = interval
        task.save()
    commands = [
        [
            sys.executable,
            str(BACKEND / "manage.py"),
            "worker",
            "--kind",
            "io",
            "--concurrency",
            "1",
        ],
        [
            sys.executable,
            str(BACKEND / "manage.py"),
            "worker",
            "--kind",
            "cpu",
            "--concurrency",
            "1",
        ],
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "papilio_panel.config.celery:app",
            "beat",
            "--loglevel=INFO",
            "--max-interval=1",
            f"--pidfile={tmp_path / 'beat.pid'}",
        ],
    ]
    logs = [(tmp_path / f"process-{index}.log").open("w") for index in range(len(commands))]
    processes = [
        subprocess.Popen(
            command, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
        for command, log in zip(commands, logs, strict=True)
    ]
    try:
        yield
    finally:
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        app.control.purge()
        for log in logs:
            log.close()


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
