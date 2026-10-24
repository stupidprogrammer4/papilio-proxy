"""Browser to native Django, Beat, worker, mTLS agent, Xray and actual client."""

import json
import os
import signal
import subprocess
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from conftest import until
from django.contrib.auth.models import User
from django.db import connection
from recovery_browser_scenario import browser_recovery_scenario
from test_node_runtime import listening, port
from test_node_user_control import native_control as native_control
from test_service_runtime import existing_owner_client
from xray_client import subscription_client

from papilio_panel.modules.nodes.domain import XrayApply
from papilio_panel.modules.payments.models import Invoice, PaymentDecision, Receipt
from papilio_panel.modules.services.models import ServiceAccount
from papilio_panel.modules.shop.models import (
    InboxWork,
    MessageRecovery,
    OutgoingMessage,
    ShopConfiguration,
    WorkRecovery,
)
from papilio_panel.modules.wallets.models import JournalEntry, Wallet

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.runtime]
ROOT = Path(__file__).resolve().parents[3]


def stop_browser_process(process: subprocess.Popen) -> None:
    """Stop only the new session created for this test's server or preview."""
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


@pytest.mark.timeout(120)
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
    with (
        browser_recovery_scenario(existing_owner_client()) as scenario,
        (tmp_path / "browser-server.log").open("w") as log,
        tempfile.TemporaryDirectory(prefix="papilio-browser-", dir="/tmp") as control_folder,
    ):
        env["PAPILIO_RECOVERY_BOT_ID"] = str(scenario.bot_id)
        env["PAPILIO_RECOVERY_WORK_ID"] = str(scenario.work_id)
        env["PAPILIO_RECOVERY_MESSAGE_ID"] = str(scenario.message_id)
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
                "--control-socket",
                str(Path(control_folder) / "gunicorn.sock"),
            ],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        frontend = None
        try:
            assert os.getpgid(web.pid) == web.pid
            until(
                lambda: (
                    listening(backend_port) and (Path(control_folder) / "gunicorn.sock").exists()
                ),
                timeout=10,
            )
            frontend = subprocess.Popen(
                ["pnpm", "--filter", "@papilio/panel", "preview"],
                cwd=ROOT / "panel/frontend",
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            assert os.getpgid(frontend.pid) == frontend.pid
            until(lambda: listening(frontend_port), timeout=10)
            result = subprocess.run(
                ["node", "tests/service-provisioning.browser.mjs"],
                cwd=ROOT / "panel/frontend",
                env=env,
                capture_output=True,
                text=True,
                timeout=85,
            )
            assert result.returncode == 0, result.stderr
            output = json.loads(result_path.read_text())
            connection.close()
            assert InboxWork.objects.get(pk=scenario.work_id).status == "cancelled"
            recovered_message = OutgoingMessage.objects.get(pk=scenario.message_id)
            assert recovered_message.status == "sent"
            assert bytes(recovered_message.payload_ciphertext) == scenario.message_ciphertext
            assert WorkRecovery.objects.get(work_id=scenario.work_id).action == "cancel"
            assert MessageRecovery.objects.get(message_id=scenario.message_id).action == "retry"
            first_shop = ShopConfiguration.objects.get(bot_id=output["shops"]["first"])
            second_shop = ShopConfiguration.objects.get(bot_id=output["shops"]["second"])
            assert first_shop.revision == 2 and first_shop.enabled is False
            assert first_shop.delivery_enabled is False and first_shop.retry_seconds == 17
            assert first_shop.texts["en"]["welcome"] == "Private shop $name"
            assert first_shop.texts["fa"]["welcome"] == "فروشگاه $name"
            assert second_shop.public_origin == "https://shop-two.example.invalid"
            assert second_shop.enabled is False and second_shop.texts != first_shop.texts
            service = ServiceAccount.objects.get(pk=output["service_id"])
            assert service.status == "succeeded" and service.worker_pid != os.getpid()
            assert service.sync_enabled is False and service.sync_interval_seconds == 7
            assert service.sync_revision == 4
            wallet = Wallet.objects.get(customer_id=output["customer_id"])
            assert wallet.balance_minor == 0 and wallet.credit_limit_minor == 75
            assert JournalEntry.objects.filter(wallet=wallet).count() == 4
            invoice = Invoice.objects.get(pk=output["invoice_id"])
            assert invoice.status == "settled" and invoice.base_amount_minor == 1000
            assert invoice.destination == "TEST-ACCOUNT-ORIGINAL"
            payment = PaymentDecision.objects.get(invoice=invoice)
            assert payment.wallet_entry_id is not None and payment.receipt_id is not None
            assert JournalEntry.objects.get(pk=payment.wallet_entry_id).request_key == invoice.id
            assert (
                bytes(Receipt.objects.get(pk=payment.receipt_id).content)
                == b"controlled-private-receipt"
            )
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
                stop_browser_process(frontend)
            stop_browser_process(web)
