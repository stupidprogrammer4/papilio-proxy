"""Actual owned queue outage and native outer-commit checkout recovery."""

import asyncio
import copy
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from papilio.infra.db.transaction import transaction
from papilio.infra.db.uow import MySQLUnitOfWork
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from taskiq.exceptions import SendTaskError

from src.modules.billing.wallet.domain.dtos import TopupApproval
from src.modules.billing.wallet.interfaces import IWalletCommand
from src.modules.sales.checkout.interfaces import ICheckoutFundingPublisher
from tests.scheduler_runtime import _exercise_native_runtime
from tests.test_checkout_workflow import CheckoutWorkflowTest


def start_owned_queue_redis(directory, port):
    log = Path(directory) / "redis.log"
    log.touch(mode=0o600)
    with log.open("a") as output:
        process = subprocess.Popen(
            [
                "redis-server",
                "--bind",
                "127.0.0.1",
                "--port",
                str(port),
                "--dir",
                directory,
                "--save",
                "",
                "--appendonly",
                "no",
            ],
            stdout=output,
            stderr=output,
        )
    client = Redis(
        host="127.0.0.1", port=port, socket_timeout=1, socket_connect_timeout=1
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError("Owned Redis did not start")
            try:
                if client.ping():
                    return process
            except RedisError:
                continue
        raise AssertionError("Owned Redis readiness deadline")
    except BaseException:
        process.terminate()
        process.wait(timeout=5)
        raise
    finally:
        client.close()


def stop_owned_queue_redis(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


class CheckoutPublicationWorkflowTest(CheckoutWorkflowTest):
    async def test_outer_commit_guard_real_queue_outage_and_scanner_recovery(
        self,
    ):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        with tempfile.TemporaryDirectory(
            prefix="papilio-checkout-queue-test-"
        ) as directory:
            Path(directory).chmod(0o700)
            process = await asyncio.to_thread(
                start_owned_queue_redis, directory, port
            )
            try:
                # API authentication/cache still use the fixture Redis6384.
                # Only the native producer uses the owned Redis.
                queue_url = f"redis://127.0.0.1:{port}/0"
                self.raw["tasks"]["scheduler"]["url"] = queue_url
                await self.enable_manual_checkout()
                _, _, _, intent = await self.pending_intent("outage")
                async with self.connection.uow() as unit:
                    result = await unit.execute(
                        text("SELECT MIN(id) FROM tbl_staff")
                    )
                    staff_id = result.scalar_one()
                with self.assertRaisesRegex(
                    RuntimeError, "requires confirmed native commit"
                ):
                    async with self.app.state.dishka_container() as scope:
                        unit = await scope.get(MySQLUnitOfWork)
                        async with transaction(unit):
                            wallets = await scope.get(IWalletCommand)
                            await wallets.approve(
                                intent["topup_id"],
                                TopupApproval(
                                    expected_revision=1,
                                    bank_reference="outer_" + self.suffix,
                                ),
                                staff_id,
                            )
                            publisher = await scope.get(
                                ICheckoutFundingPublisher
                            )
                            await publisher.publish(intent["topup_id"])
                async with self.connection.uow() as unit:
                    result = await unit.execute(
                        text("SELECT status FROM tbl_topups WHERE id=:id"),
                        {"id": intent["topup_id"]},
                    )
                    self.assertEqual(result.scalar_one(), "pending")
                    result = await unit.execute(
                        text(
                            "SELECT COUNT(*) FROM tbl_wallet_entries e "
                            "JOIN tbl_wallets w ON w.id=e.wallet_id WHERE "
                            "w.customer_id=:id"
                        ),
                        {"id": intent["customer_id"]},
                    )
                    self.assertEqual(result.scalar_one(), 0)
                await asyncio.to_thread(stop_owned_queue_redis, process)
                approval_response = None
                approval_error = None
                try:
                    approval_response = await self.client.post(
                        f"/v1/admin/payments/topups/{intent['topup_id']}/approve",
                        headers=self.headers,
                        json={
                            "expected_revision": 1,
                            "bank_reference": "outage_" + self.suffix,
                        },
                    )
                except SendTaskError as error:
                    approval_error = error
                async with self.connection.uow() as unit:
                    result = await unit.execute(
                        text(
                            "SELECT t.status,w.balance_rial,"
                            "SUM(e.reason='approved_topup') credits,"
                            "SUM(e.reason='purchase') debits,"
                            "i.subscription_id "
                            "FROM tbl_topups t JOIN tbl_wallets w "
                            "ON w.customer_id=t.customer_id "
                            "JOIN tbl_wallet_entries e ON e.wallet_id=w.id "
                            "JOIN tbl_checkout_intents i ON i.topup_id=t.id "
                            "WHERE t.id=:id GROUP BY "
                            "t.status,w.balance_rial,i.subscription_id"
                        ),
                        {"id": intent["topup_id"]},
                    )
                    self.assertEqual(
                        tuple(result.one()), ("approved", 120000, 1, 0, None)
                    )
                self.assertIsNone(approval_error)
                self.assertIsNotNone(approval_response)
                assert approval_response is not None
                self.assertEqual(
                    approval_response.status_code, 200, approval_response.text
                )
                self.assertEqual(
                    approval_response.json()["data"]["status"], "approved"
                )
                replay = await self.post(
                    f"/v1/admin/payments/topups/{intent['topup_id']}/approve",
                    {
                        "expected_revision": 1,
                        "bank_reference": "outage_" + self.suffix,
                    },
                )
                self.assertEqual(replay["status"], "approved")
                async with self.app.state.dishka_container() as scope:
                    publisher = await scope.get(ICheckoutFundingPublisher)
                    self.assertFalse(
                        await publisher.publish(intent["topup_id"])
                    )
                async with self.connection.uow() as unit:
                    result = await unit.execute(
                        text(
                            "SELECT balance_rial FROM tbl_wallets WHERE "
                            "customer_id=:id"
                        ),
                        {"id": intent["customer_id"]},
                    )
                    self.assertEqual(result.scalar_one(), 120000)
                    result = await unit.execute(
                        text(
                            "SELECT subscription_id FROM "
                            "tbl_checkout_intents WHERE id=:id"
                        ),
                        {"id": intent["id"]},
                    )
                    self.assertIsNone(result.scalar_one())
                process = await asyncio.to_thread(
                    start_owned_queue_redis, directory, port
                )
                recovery = copy.deepcopy(self.raw)
                recovery["redis"]["url"] = queue_url
                outcome = await asyncio.to_thread(
                    _exercise_native_runtime,
                    recovery,
                    "SELECT "
                    "i.state,w.balance_rial,SUM(e.reason='purchase') "
                    "debits,"
                    "SUM(e.reason='approved_topup') credits FROM "
                    "tbl_checkout_intents i "
                    "JOIN tbl_wallets w ON w.customer_id=i.customer_id "
                    "JOIN tbl_wallet_entries e ON e.wallet_id=w.id WHERE "
                    "i.id=%s "
                    "GROUP BY i.state,w.balance_rial",
                    (intent["id"],),
                    lambda row: row["state"] == "purchased",
                    ("state", "balance_rial", "debits", "credits"),
                    ("ScanCheckouts", "RecoverCheckout", "PrepareProvision"),
                    owned_namespace=self.checkout_namespace,
                )
                self.assertEqual(outcome, ("purchased", 20000, 1, 1))
            finally:
                await asyncio.to_thread(stop_owned_queue_redis, process)
