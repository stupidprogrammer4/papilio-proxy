"""Browser to native Django, Beat, worker, mTLS agent, Xray and actual client."""

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from conftest import until
from django.contrib.auth.models import User
from django.db import connection
from test_node_runtime import listening, port, stop
from test_node_user_control import native_control as native_control
from xray_client import subscription_client

from papilio_panel.modules.nodes.domain import XrayApply
from papilio_panel.modules.services.models import ServiceAccount
from papilio_panel.modules.wallets.models import JournalEntry, Wallet

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.runtime]
ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.timeout(100)
@pytest.mark.skipif(
    os.environ.get("PAPILIO_RUN_SERVICE_BROWSER") != "1",
    reason="Enable the native service browser gate after building the frontend.",
)
def test_panel_provisions_a_service_used_by_an_actual_native_client(
    native_control: tuple[XrayApply, int, str], tmp_path: Path
) -> None:
    _, data_port, binary = native_control
    User.objects.create_user(
        username="service-browser-staff",
        password="isolated-node-owner-password-944!",
        is_staff=True,
    )
    backend_port, frontend_port = port(), port()
    env = os.environ.copy()
    database = str(connection.settings_dict["NAME"])
    assert database.startswith("test_")
    parsed = urlsplit(env["DATABASE_URL"])
    env["DATABASE_URL"] = urlunsplit(parsed._replace(path="/" + database))
    env["PAPILIO_TRUSTED_ORIGINS"] = f"http://127.0.0.1:{frontend_port}"
    env["PAPILIO_BACKEND_URL"] = f"http://127.0.0.1:{backend_port}"
    env["PAPILIO_PANEL_PORT"] = str(frontend_port)
    env["PAPILIO_BROWSER_URL"] = f"http://127.0.0.1:{frontend_port}"
    result_path = tmp_path / "browser-result.json"
    env["PAPILIO_BROWSER_RESULT"] = str(result_path)
    env["PAPILIO_BROWSER_DATA_PORT"] = str(data_port)
    with (tmp_path / "browser-server.log").open("w") as log:
        web = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "gunicorn",
                "papilio_panel.config.wsgi:application",
                "--bind",
                f"127.0.0.1:{backend_port}",
                "--workers",
                "1",
            ],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        frontend = None
        try:
            until(lambda: listening(backend_port), timeout=10)
            frontend = subprocess.Popen(
                ["pnpm", "--filter", "@papilio/panel", "preview"],
                cwd=ROOT / "panel/frontend",
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            until(lambda: listening(frontend_port), timeout=10)
            result = subprocess.run(
                ["node", "tests/service-provisioning.browser.mjs"],
                cwd=ROOT / "panel/frontend",
                env=env,
                capture_output=True,
                text=True,
                timeout=65,
            )
            assert result.returncode == 0, result.stderr
            output = json.loads(result_path.read_text())
            connection.close()
            service = ServiceAccount.objects.get(pk=output["service_id"])
            assert service.status == "succeeded" and service.worker_pid != os.getpid()
            wallet = Wallet.objects.get(customer_id=output["customer_id"])
            assert wallet.balance_minor == 0 and wallet.credit_limit_minor == 75
            assert JournalEntry.objects.filter(wallet=wallet).count() == 4
            assert (
                JournalEntry.objects.filter(wallet=wallet, amount_minor=9007199254740993).count()
                == 2
            )
            with subscription_client(binary, tmp_path, output["uri"]) as probe:
                assert probe.fetch() == b"papilio-actual-subscription-client"
            with subscription_client(binary, tmp_path, output["purchase"]["uri"]) as probe:
                assert probe.fetch() == b"papilio-actual-subscription-client"
        finally:
            if frontend is not None:
                stop(frontend)
            stop(web)
