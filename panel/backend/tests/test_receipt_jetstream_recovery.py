import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import nats
import pytest
from faststream.nats import NatsBroker as NativeNatsBroker
from nats.js.errors import NotFoundError
from papilio_tasks.apps.events.application import create_app
from papilio_tasks.apps.events.registry.jetstream import JetRegistrar
from papilio_tasks.infra.faststream.brokers.backends.nats import NatsBroker

from src.modules.billing.receipts.domain.events import ReceiptOcrRequest
from src.modules.billing.receipts.tasks.events import ReceiptOcrRequested

pytestmark = [pytest.mark.billing, pytest.mark.integration]
_BACKEND = Path(__file__).resolve().parents[1]
_WORKER = _BACKEND / "tests" / "receipt_ocr_jetstream_worker.py"


def test_jetstream_redelivers_after_worker_process_is_killed(tmp_path):
    url = os.environ.get("NATS_TEST_URL")
    if url is None:
        pytest.skip("Set NATS_TEST_URL to an isolated JetStream test server")

    first_result = tmp_path / "first-worker.txt"
    second_result = tmp_path / "second-worker.txt"
    asyncio.run(_purge_test_stream(url))
    first = subprocess.Popen(
        [sys.executable, str(_WORKER), url, str(first_result), "block"],
        cwd=_BACKEND,
    )
    try:
        _wait_for_consumer(url, first)
        asyncio.run(_publish_receipt(url))
        _wait_for_file(first_result, first)
        first.kill()
        first.wait(timeout=10)

        second = subprocess.Popen(
            [
                sys.executable,
                str(_WORKER),
                url,
                str(second_result),
                "complete",
            ],
            cwd=_BACKEND,
        )
        try:
            _wait_for_file(second_result, second)
            assert second_result.read_text(encoding="utf-8") == "41"
        finally:
            second.kill()
            second.wait(timeout=10)
    finally:
        if first.poll() is None:
            first.kill()
            first.wait(timeout=10)
        asyncio.run(_delete_test_consumer(url))


async def _publish_receipt(url: str) -> None:
    broker = NatsBroker(NativeNatsBroker(url))
    registrar = JetRegistrar(broker)
    registrar.publisher(ReceiptOcrRequested)
    app = create_app(registrar=registrar)
    await app.connect()
    try:
        await ReceiptOcrRequested.publish(ReceiptOcrRequest(receipt_id=41))
    finally:
        await app.stop()


async def _delete_test_consumer(url: str) -> None:
    client = await nats.connect(url)
    try:
        jetstream = client.jetstream()
        try:
            await jetstream.delete_consumer(
                "receipt-ocr", "receipt-ocr-kill-test"
            )
        except NotFoundError:
            pass
        await jetstream.purge_stream("receipt-ocr")
    finally:
        await client.close()


async def _purge_test_stream(url: str) -> None:
    broker = NatsBroker(NativeNatsBroker(url))
    registrar = JetRegistrar(broker)
    registrar.publisher(ReceiptOcrRequested)
    app = create_app(registrar=registrar)
    await app.start()
    client = await nats.connect(url)
    try:
        await client.jetstream().purge_stream("receipt-ocr")
    finally:
        await client.close()
        await app.stop()


def _wait_for_consumer(url: str, process: subprocess.Popen[bytes]) -> None:
    async def inspect() -> bool:
        client = await nats.connect(url, connect_timeout=1)
        try:
            await client.jetstream().consumer_info(
                "receipt-ocr", "receipt-ocr-kill-test"
            )
        finally:
            await client.close()
        return True

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError("JetStream worker exited before subscribing")
        try:
            if asyncio.run(inspect()):
                return
        except Exception:
            time.sleep(0.1)
    raise AssertionError("JetStream durable consumer did not become ready")


def _wait_for_file(path: Path, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if path.is_file():
            return
        if process.poll() is not None:
            raise AssertionError("JetStream worker exited before processing")
        time.sleep(0.05)
    raise AssertionError("JetStream worker did not process the receipt")
