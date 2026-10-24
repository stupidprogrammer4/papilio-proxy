"""Native cancelled receipt work survives an actual test-owned broker outage."""

import os
import subprocess
from datetime import timedelta
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from conftest import until
from django.utils import timezone
from telegram_server import TelegramServer
from test_nodes import owner_client
from test_shop_payments import payment_bot

from papilio_panel.modules.payments.models import Receipt
from papilio_panel.modules.shop.models import InboxWork

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.runtime]


def process_exited(pid: int) -> bool:
    """A cancelled child may remain a zombie until its reconnecting parent reaps it."""
    try:
        status = Path(f"/proc/{pid}/status").read_text()
    except FileNotFoundError:
        return True
    return any(line.startswith("State:\tZ") for line in status.splitlines())


@pytest.mark.timeout(120)
def test_receipt_retry_recovers_after_broker_outage_without_credit(runtime: None) -> None:
    container = os.environ.get("PAPILIO_TEST_BROKER_CONTAINER")
    if not container:
        pytest.skip("Explicitly test-owned RabbitMQ is required for this fault boundary.")
    server = TelegramServer()
    stopped = Event()

    def stop_broker_during_download() -> None:
        subprocess.run(
            ["docker", "exec", container, "rabbitmqctl", "stop_app"],
            check=True,
            capture_output=True,
            timeout=30,
        )
        stopped.set()

    with server.running() as address:
        owner = owner_client("receipt-fault-owner")
        bot, customer = payment_bot(owner, server, address)
        root = f"/api/v1/bots/{bot}"
        current = owner.get(root).json()
        assert (
            owner.put(
                root,
                {
                    "expected_revision": current["revision"],
                    "label": current["label"],
                    "runtime": current["runtime"]
                    | {"poll_timeout_seconds": 1, "http_timeout_seconds": 6},
                    "schedule": {"enabled": True, "interval_seconds": 1},
                },
                format="json",
            ).status_code
            == 200
        )
        policy = owner.get(root + "/shop").json()
        assert (
            owner.put(
                root + "/shop",
                policy["definition"]
                | {
                    "expected_revision": policy["revision"],
                    "retry_seconds": 1,
                },
                format="json",
            ).status_code
            == 200
        )
        issued = owner.post(
            "/api/v1/invoices",
            {
                "request_key": str(uuid4()),
                "customer_id": customer,
                "base_amount_minor": "1000",
            },
            format="json",
        )
        assert issued.status_code == 201
        invoice = issued.json()
        server.files["photos/fault-proof.jpg"] = b"controlled-broker-recovery-receipt"
        server.file_statuses = [503]
        server.download_observer = stop_broker_during_download
        try:
            server.push_photo(2, "fault-proof", chat_id=987654, caption=f"/receipt {invoice['id']}")
            until(
                lambda: (
                    stopped.is_set()
                    and InboxWork.objects.filter(
                        event__bot_id=bot,
                        event__update_id=2,
                        status="running",
                        worker_pid__isnull=False,
                    ).exists()
                ),
                timeout=35,
            )
            retained = InboxWork.objects.get(event__bot_id=bot, event__update_id=2)
            assert retained.worker_pid is not None and retained.worker_pid != os.getpid()
            cancelled_pid = retained.worker_pid
            until(lambda: process_exited(cancelled_pid), timeout=10)
            assert retained.attempts == 1 and retained.event.processed_at is None
            assert Receipt.objects.count() == 0
            # Native Celery cancels late-ack work on broker loss. Advance only this
            # dead test worker's lease to exercise the actual outbox reclaim path.
            InboxWork.objects.filter(pk=retained.id).update(
                lease_until=timezone.now() - timedelta(seconds=1)
            )
        finally:
            server.download_observer = None
            subprocess.run(
                ["docker", "exec", container, "rabbitmqctl", "start_app"],
                check=True,
                capture_output=True,
                timeout=30,
            )
        until(lambda: Receipt.objects.filter(invoice_id=invoice["id"]).exists(), timeout=35)
        retained.refresh_from_db()
        assert retained.status == "done" and retained.attempts == 2
        assert retained.worker_pid != os.getpid() and retained.event.processed_at is not None
        evidence = Receipt.objects.get(invoice_id=invoice["id"])
        assert evidence.request_key == retained.id
        assert bytes(evidence.content) == b"controlled-broker-recovery-receipt"
        assert server.file_calls == ["photos/fault-proof.jpg", "photos/fault-proof.jpg"]
        wallet = f"/api/v1/customer-accounts/{customer}/wallet"
        assert owner.get(wallet).json()["balance_minor"] == "0"
        assert owner.get(wallet + "/entries").json()["count"] == 0
