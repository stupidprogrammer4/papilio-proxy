"""Real isolated worker/Beat lifecycle shared by runtime acceptance tests."""

import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from django.db import connection
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from papilio_panel.config.celery import app

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
        # Outage tests deliberately invalidate any previously pooled connection.
        with app.connection_for_write() as broker:
            app.control.purge(connection=broker)
        for log in logs:
            log.close()
