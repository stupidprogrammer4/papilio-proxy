import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import pymysql
import yaml
from sqlalchemy.engine import make_url


def exercise_native_schedulers(raw, topup_id, node_id, subscription_id):
    query = (
        "SELECT p.status AS payment_status, n.status AS node_status, "
        "s.renewal_count FROM tbl_payment_reviews p "
        "JOIN tbl_node_health n ON n.node_id=%s "
        "JOIN tbl_subscriptions s ON s.id=%s "
        "JOIN tbl_subscription_attention a ON a.subscription_id=s.id "
        "WHERE p.topup_id=%s"
    )
    return _exercise_native_runtime(
        raw,
        query,
        (node_id, subscription_id, topup_id),
        lambda row: row["renewal_count"] == 1,
        ("payment_status", "node_status", "renewal_count"),
        (
            "CheckPaymentReview",
            "CheckNodeHealth",
            "CheckSubscriptionAttention",
            "RenewSubscription",
        ),
    )


def exercise_native_provisioning(raw, request_id):
    query = (
        "SELECT r.state, COUNT(t.id) AS tasks FROM tbl_provision_requests r "
        "LEFT JOIN tbl_provision_tasks t ON t.request_id=r.id "
        "WHERE r.id=%s GROUP BY r.id, r.state"
    )

    return _exercise_native_runtime(
        raw,
        query,
        (request_id,),
        lambda row: row["state"] == "dispatching" and row["tasks"] == 2,
        ("state", "tasks"),
        ("PrepareProvision",),
    )


def exercise_native_reseller_renewal(raw, subscription_id):
    return _exercise_native_runtime(
        raw,
        "SELECT renewal_count FROM tbl_subscriptions WHERE id=%s",
        (subscription_id,),
        lambda row: row["renewal_count"] == 1,
        ("renewal_count",),
        ("ScanRenewals", "RenewSubscription"),
    )


def exercise_native_reseller_attention(raw, subscription_id):
    return _exercise_native_runtime(
        raw,
        "SELECT status, payer_customer_id, renewal_price_rial, "
        "wallet_balance_rial FROM tbl_subscription_attention "
        "WHERE subscription_id=%s",
        (subscription_id,),
        lambda row: row["status"] == "renewal_unavailable",
        (
            "status",
            "payer_customer_id",
            "renewal_price_rial",
            "wallet_balance_rial",
        ),
        ("ScanSubscriptionAttention", "CheckSubscriptionAttention"),
    )


def exercise_native_lifecycle(raw, subscription_id, completion="expire"):
    query = (
        "SELECT s.status, r.completion FROM tbl_subscriptions s "
        "JOIN tbl_provision_requests r ON r.subscription_id=s.id AND "
        "r.generation=s.renewal_count WHERE s.id=%s"
    )
    return _exercise_native_runtime(
        raw,
        query,
        (subscription_id,),
        lambda row: (
            row["status"] == "revoking" and row["completion"] == completion
        ),
        ("status", "completion"),
        ("CheckSubscriptionLifecycle",),
    )


def exercise_native_customer_hold(raw, subscription_id):
    query = (
        "SELECT s.status, r.completion FROM tbl_subscriptions s "
        "JOIN tbl_provision_requests r ON r.subscription_id=s.id "
        "AND r.generation=s.renewal_count WHERE s.id=%s"
    )
    return _exercise_native_runtime(
        raw,
        query,
        (subscription_id,),
        lambda row: (
            row["status"] == "revoking" and row["completion"] == "suspend"
        ),
        ("status", "completion"),
        ("CheckCustomerHold",),
    )


def exercise_native_notifications(raw, notification_id):
    query = (
        "SELECT n.status, n.attempts, a.outcome FROM tbl_notifications n "
        "JOIN tbl_notification_attempts a ON a.notification_id=n.id "
        "AND a.attempt=n.attempts WHERE n.id=%s"
    )
    return _exercise_native_runtime(
        raw,
        query,
        (notification_id,),
        lambda row: (
            row["status"] == "delivered"
            and row["attempts"] == 1
            and row["outcome"] == "accepted"
        ),
        ("status", "attempts", "outcome"),
        ("ScanNotifications", "DeliverNotification"),
    )


def exercise_native_core_runtime(raw, command_id):
    return _exercise_native_runtime(
        raw,
        "SELECT state, attempts FROM tbl_core_runtime_commands WHERE id=%s",
        (command_id,),
        lambda row: row["state"] == "queued" and row["attempts"] == 1,
        ("state", "attempts"),
        ("ScanCoreRuntime", "RecoverCoreRuntime"),
    )


def exercise_native_loyalty_notifications(raw, notification_ids):
    placeholders = ",".join("%s" for _ in notification_ids)
    query = (
        "SELECT COUNT(*) total, SUM(n.status='delivered') delivered, "
        "MAX(n.attempts) attempts FROM tbl_notifications n "
        "JOIN tbl_notification_attempts a ON a.notification_id=n.id "
        "AND a.attempt=n.attempts AND a.outcome='accepted' "
        f"WHERE n.id IN ({placeholders})"
    )
    return _exercise_native_runtime(
        raw,
        query,
        tuple(notification_ids),
        lambda row: (
            row["total"] == len(notification_ids)
            and row["delivered"] == len(notification_ids)
            and row["attempts"] == 1
        ),
        ("total", "delivered", "attempts"),
        ("ScanNotifications", "DeliverNotification"),
    )


def exercise_native_installed_purchase(raw, request_id):
    return _exercise_native_runtime(
        raw,
        "SELECT r.state request_state, s.status subscription_status, "
        "t.state task_state, p.applied_generation, r.generation, "
        "t.installed_revision_id "
        "FROM tbl_provision_requests r "
        "JOIN tbl_subscriptions s ON s.id=r.subscription_id "
        "JOIN tbl_provision_tasks t ON t.request_id=r.id "
        "JOIN tbl_profiles p ON p.id=t.profile_id WHERE r.id=%s",
        (request_id,),
        lambda row: (
            row["request_state"] == "active"
            and row["subscription_status"] == "active"
            and row["task_state"] == "applied"
            and row["applied_generation"] == row["generation"]
            and row["installed_revision_id"] is not None
        ),
        ("request_state", "task_state", "applied_generation"),
        ("ScanProvisioning", "ScanCoreProvisioning", "EnsureCoreProvisioning"),
    )


def exercise_native_receipt_outbox(
    database_url, redis_url, nats_url, outbox_id
):
    database = make_url(database_url)
    assert database.database is not None and "test" in database.database
    assert database.username is not None and database.password is not None
    with tempfile.TemporaryDirectory(prefix="papilio-receipt-outbox-") as name:
        directory = Path(name)
        directory.chmod(0o700)
        config = yaml.safe_load(Path("config.yml.sample").read_text())
        config["db"]["dsn"] = database_url
        config["db"]["test_dsn"] = database_url
        config["redis"]["url"] = redis_url
        config["events"]["nats_url"] = nats_url
        prefix = "papilio:test:receipt-outbox:" + directory.name
        config["tasks"]["scheduler"].update(
            url=redis_url,
            queue_name=prefix + ":jobs",
            schedule_prefix=prefix + ":schedules",
            result_prefix=prefix + ":results",
        )
        config_path = directory / "config.yml"
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True))
        config_path.chmod(0o600)
        environment = {**os.environ, "PAPILIO_CONFIG": str(config_path)}
        log_path = directory / "runtime.log"
        processes = []
        connection = pymysql.connect(
            host=database.host or "127.0.0.1",
            port=database.port or 3306,
            user=database.username,
            password=database.password,
            database=database.database,
            autocommit=True,
            cursorclass=pymysql.cursors.DictCursor,
        )
        try:
            with log_path.open("w+") as output:
                log_path.chmod(0o600)
                processes.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "taskiq",
                            "worker",
                            "src.apps.scheduler:broker",
                            "--workers",
                            "1",
                            "--max-async-tasks",
                            "8",
                        ],
                        env=environment,
                        stdout=output,
                        stderr=output,
                        start_new_session=True,
                    )
                )
                processes.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "taskiq",
                            "scheduler",
                            "src.apps.scheduler:scheduler",
                            "--skip-first-run",
                            "--update-interval",
                            "1",
                        ],
                        env=environment,
                        stdout=output,
                        stderr=output,
                        start_new_session=True,
                    )
                )
                deadline = time.monotonic() + 90
                delivered = None
                while time.monotonic() < deadline:
                    exited = any(
                        process.poll() is not None for process in processes
                    )
                    if exited:
                        raise AssertionError(
                            "Native receipt outbox runtime exited early"
                        )
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT status, attempts "
                            "FROM tbl_receipt_ocr_outboxes WHERE id=%s",
                            (outbox_id,),
                        )
                        row = cursor.fetchone()
                    output.flush()
                    logs = log_path.read_text()
                    if (
                        row
                        and row["status"] == "published"
                        and "PublishReceiptOcrOutbox" in logs
                    ):
                        delivered = (row["status"], row["attempts"])
                        break
                    time.sleep(0.2)
                if delivered is None:
                    raise AssertionError(
                        "Native receipt outbox schedule did not publish"
                    )
                return delivered
        finally:
            connection.close()
            for process in processes:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGINT)
            for process in processes:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            import redis

            client = redis.Redis.from_url(redis_url)
            keys = list(client.scan_iter(match=prefix + ":*"))
            if keys:
                client.delete(*keys)
            client.close()


def _exercise_native_runtime(
    raw,
    query,
    parameters,
    complete,
    result_keys,
    expected,
    *,
    owned_namespace=None,
):
    nats_url = os.environ.get("NATS_TEST_URL")
    if not nats_url:
        raise unittest.SkipTest(
            "Set NATS_TEST_URL to an isolated NATS JetStream server"
        )
    url = make_url(raw["db"]["dsn"])
    assert url.database is not None and "test" in url.database
    assert url.username is not None and url.password is not None
    with tempfile.TemporaryDirectory(prefix="papilio-scheduler-test-") as name:
        directory = Path(name)
        directory.chmod(0o700)
        config = yaml.safe_load(yaml.safe_dump(raw))
        config["events"]["nats_url"] = nats_url
        prefix = "papilio:test:" + directory.name
        if owned_namespace is not None:
            import re

            if (
                re.fullmatch(r"papilio:test:[A-Za-z0-9:_-]+", owned_namespace)
                is None
            ):
                raise ValueError(
                    "Only an explicit test-owned namespace is allowed"
                )
            expected_prefixes = {
                "queue_name": owned_namespace + ":jobs",
                "schedule_prefix": owned_namespace + ":schedules",
                "result_prefix": owned_namespace + ":results",
            }
            if any(
                config["tasks"]["scheduler"].get(key) != value
                for key, value in expected_prefixes.items()
            ):
                raise ValueError(
                    "Producer prefixes do not match owned namespace"
                )
            prefix = owned_namespace
        config["tasks"]["scheduler"].update(
            url=config["redis"]["url"],
            queue_name=prefix + ":jobs",
            schedule_prefix=prefix + ":schedules",
            result_prefix=prefix + ":results",
        )
        config["operations"].update(
            payment_scan_cron="* * * * *",
            node_health_scan_cron="* * * * *",
            subscription_attention_scan_cron="* * * * *",
            renewal_scan_cron="* * * * *",
            lifecycle_scan_cron="* * * * *",
            node_health_stale_seconds=300,
        )
        config["fulfillment"].update(scan_cron="* * * * *", recheck_seconds=1)
        if config.get("core_runtime") is not None:
            config["core_runtime"]["scan_cron"] = "* * * * *"
        if config.get("core_provisioning") is not None:
            config["core_provisioning"]["scan_cron"] = "* * * * *"
        config_path = directory / "config.yml"
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True))
        config_path.chmod(0o600)
        env = {**os.environ, "PAPILIO_CONFIG": str(config_path)}
        log_path = directory / "runtime.log"
        processes = []
        connection = pymysql.connect(
            host=url.host or "127.0.0.1",
            port=url.port or 3306,
            user=url.username,
            password=url.password,
            database=url.database,
            autocommit=True,
            cursorclass=pymysql.cursors.DictCursor,
        )
        try:
            with log_path.open("w+") as output:
                log_path.chmod(0o600)
                assert os.getloadavg()[0] <= 8, "Worker load preflight failed"
                processes.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "taskiq",
                            "worker",
                            "src.apps.scheduler:broker",
                            "--workers",
                            "1",
                            "--max-async-tasks",
                            "8",
                        ],
                        env=env,
                        stdout=output,
                        stderr=output,
                        start_new_session=True,
                    )
                )
                assert os.getloadavg()[0] <= 8, "Beat load preflight failed"
                processes.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "taskiq",
                            "scheduler",
                            "src.apps.scheduler:scheduler",
                            "--skip-first-run",
                            "--update-interval",
                            "1",
                        ],
                        env=env,
                        stdout=output,
                        stderr=output,
                        start_new_session=True,
                    )
                )
                deadline = time.monotonic() + 90
                seen = None
                while time.monotonic() < deadline:
                    if any(
                        process.poll() is not None for process in processes
                    ):
                        raise AssertionError(
                            "Native runtime exited before the business outcome"
                        )
                    with connection.cursor() as cursor:
                        cursor.execute(query, parameters)
                        row = cursor.fetchone()
                    output.flush()
                    if (
                        row
                        and complete(row)
                        and all(
                            name in log_path.read_text() for name in expected
                        )
                    ):
                        seen = tuple(row[key] for key in result_keys)
                        break
                    time.sleep(0.2)
                if seen is None:
                    diagnostics = (
                        Path(__file__).resolve().parents[3]
                        / "data"
                        / "automation-runtime-failure.log"
                    )
                    diagnostics.write_text(log_path.read_text())
                    diagnostics.chmod(0o600)
                    raise AssertionError(
                        "Scheduled outcomes did not finish within 90 seconds"
                    )
                output.flush()
                logs = log_path.read_text()
                assert all(name in logs for name in expected), (
                    "Expected worker executions missing"
                )
                return seen
        finally:
            connection.close()
            for process in processes:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGINT)
            for process in processes:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            # Remove only this test's namespace, using explicit key ownership.
            import redis

            client = redis.Redis.from_url(config["redis"]["url"])
            keys = list(client.scan_iter(match=prefix + ":*"))
            if keys:
                client.delete(*keys)
            client.close()
