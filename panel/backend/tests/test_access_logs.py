"""Actual Docker-entrypoint Gunicorn access logs exclude private query/referrer data."""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from conftest import until
from django.db import connection
from test_node_runtime import listening, port, stop

pytestmark = pytest.mark.django_db(transaction=True)
ROOT = Path(__file__).resolve().parents[3]


def test_native_access_log_keeps_path_and_status_without_query_or_referrer(tmp_path: Path) -> None:
    command_text = next(
        line.removeprefix("CMD ")
        for line in (ROOT / "deployment/backend.Dockerfile").read_text().splitlines()
        if line.startswith("CMD ")
    )
    docker_command = json.loads(command_text)
    assert docker_command[0] == "gunicorn"
    env = os.environ.copy()
    database = str(connection.settings_dict["NAME"])
    assert database.startswith("test_")
    parsed = urlsplit(env["DATABASE_URL"])
    env["DATABASE_URL"] = urlunsplit(parsed._replace(path="/" + database))
    number = port()
    access_path = tmp_path / "access.log"
    command = [
        sys.executable,
        "-m",
        "gunicorn",
        *docker_command[1:],
        "--bind",
        f"127.0.0.1:{number}",
        "--workers",
        "1",
        "--access-logfile",
        str(access_path),
    ]
    with (tmp_path / "server.log").open("w") as log:
        server = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            until(lambda: listening(number), timeout=10)
            request = urllib.request.Request(
                f"http://127.0.0.1:{number}/api/v1/subscriptions?token=query-log-sentinel",
                headers={"Referer": "https://example.invalid/?token=referrer-log-sentinel"},
            )
            with pytest.raises(urllib.error.HTTPError) as response:
                urllib.request.urlopen(request, timeout=5)
            assert response.value.code == 404
            response.value.close()
        finally:
            stop(server)
    contents = access_path.read_text()
    assert "GET /api/v1/subscriptions" in contents and "404" in contents
    assert "query-log-sentinel" not in contents
    assert "referrer-log-sentinel" not in contents
