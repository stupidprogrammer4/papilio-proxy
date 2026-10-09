"""Real runtime failure, acknowledged retirement and native wallet refund."""

import json
import os
import signal
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from tests.core_provisioning_agent import _data, _stop_core
from tests.scheduler_runtime import _exercise_native_runtime


def exercise_native_core_purchase_failure(raw, request_id, core_id):
    return _exercise_native_runtime(
        raw,
        "SELECT r.state request_state, s.status subscription_status, "
        "t.state task_state, p.applied_generation, "
        "EXISTS(SELECT 1 FROM tbl_core_runtime_commands c "
        "WHERE c.core_id=%s AND c.purpose='provisioning' "
        "AND c.state='failed' AND c.error_code='core_validation_failed') "
        "core_failed FROM tbl_provision_requests r "
        "JOIN tbl_subscriptions s ON s.id=r.subscription_id "
        "JOIN tbl_provision_tasks t ON t.request_id=r.id "
        "JOIN tbl_profiles p ON p.id=t.profile_id WHERE r.id=%s",
        (core_id, request_id),
        lambda row: (
            row["core_failed"]
            and row["subscription_status"] == "pending_provision"
            and row["applied_generation"] is None
            and row["task_state"] != "applied"
        ),
        ("subscription_status", "applied_generation", "core_failed"),
        ("ScanProvisioning", "ScanCoreProvisioning", "EnsureCoreProvisioning"),
    )


def exercise_native_failed_purchase_refund(raw, request_id):
    return _exercise_native_runtime(
        raw,
        "SELECT r.state request_state, s.status subscription_status, "
        "t.state task_state, t.installed_revision_id, "
        "w.balance_rial, (SELECT COUNT(*) FROM tbl_wallet_entries e "
        "WHERE e.wallet_id=w.id AND e.reason='provision_refund') "
        "refund_count FROM tbl_provision_requests r "
        "JOIN tbl_subscriptions s ON s.id=r.subscription_id "
        "JOIN tbl_provision_tasks t ON t.request_id=r.id "
        "JOIN tbl_wallets w ON w.customer_id=s.customer_id WHERE r.id=%s",
        (request_id,),
        lambda row: (
            row["request_state"] == "refunded"
            and row["subscription_status"] == "failed"
            and row["task_state"] == "revoked"
            and row["installed_revision_id"] is not None
            and row["balance_rial"] == 300000
            and row["refund_count"] == 1
        ),
        ("request_state", "task_state", "balance_rial", "refund_count"),
        ("ScanProvisioning", "ScanCoreProvisioning", "EnsureCoreProvisioning"),
    )


def exercise_failed_purchase(
    directory,
    binary,
    binaries,
    base_url,
    admin_headers,
    node,
    core,
    runtime,
    scheduler_raw,
    subscription_id,
    request_id,
    telegram_id,
):
    sample = (
        Path(__file__).resolve().parents[3]
        / "proxy/runtime.config.sample.json"
    )
    config = json.loads(sample.read_text())
    config.update(
        enabled=True,
        api_url=base_url,
        node_code=node["node"]["code"],
        state_directory=str(directory / "failure-journal"),
        binaries={
            "xray": str(binaries / "xray"),
            "sing_box": str(binaries / "sing-box"),
        },
        poll_interval_ms=50,
        http_timeout_ms=5000,
        startup_grace_ms=150,
        stop_timeout_ms=2000,
        max_cores=4,
        max_processes=4,
    )
    config["provisioning"].update(
        mode="installed_only",
        max_memberships=16,
        max_receipts=32,
        page_size=16,
        max_pages_per_core=4,
        max_tasks_per_poll=32,
    )
    config_path = directory / "failure-agent.json"
    config_path.write_text(json.dumps(config))
    config_path.chmod(0o600)
    log_path = directory / "failure-agent.log"
    runtime_path = f"/v1/admin/network/cores/{core['id']}/runtime"
    with (
        httpx.Client(
            base_url=base_url,
            headers=admin_headers,
            timeout=10,
            trust_env=False,
            follow_redirects=False,
        ) as api,
        httpx.Client(
            base_url=base_url,
            timeout=10,
            trust_env=False,
            follow_redirects=False,
        ) as customer,
        log_path.open("w+") as log,
    ):
        log_path.chmod(0o600)
        configurations = _data(
            api.get(
                "/v1/admin/network/configurations",
                params={"core_id": core["id"]},
            ),
            "Owned configuration read failed",
        )
        assert len(configurations) == 1, "Unexpected owned inbound count"
        configuration = configurations[0]
        config_api = (
            f"/v1/admin/network/configurations/{configuration['id']}"
            "/server-json"
        )
        broken = _data(
            api.put(
                config_api,
                json={
                    "expected_revision": configuration["revision"],
                    "reason": "Owned actual-core rejection acceptance",
                    "document": {
                        "mode": "managed",
                        "source": json.dumps(
                            {
                                "inbounds": [{"$papilio": "managed"}],
                                "outbounds": [
                                    {
                                        "tag": "broken",
                                        "type": "unsupported",
                                        "protocol": "unsupported",
                                    }
                                ],
                            }
                        ),
                    },
                },
            ),
            "Invalid managed JSON save failed",
        )
        process = subprocess.Popen(
            [str(binary), "-config", str(config_path)],
            env={**os.environ, "PAPILIO_NODE_KEY": node["agent_key"]},
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        try:
            failure = exercise_native_core_purchase_failure(
                scheduler_raw, request_id, core["id"]
            )
            assert failure == ("pending_provision", None, 1), (
                "Core rejection did not preserve paid pending purchase"
            )
            assert process.poll() is None, "Owned runtime exited"
            subscription = _data(
                api.get(f"/v1/admin/subscriptions/{subscription_id}"),
                "Pending subscription read failed",
            )
            wallet_path = (
                f"/v1/admin/payments/wallets/{subscription['customer_id']}"
            )
            assert (
                _data(api.get(wallet_path), "Wallet read failed")[
                    "balance_rial"
                ]
                == 200000
            ), "Failed validation prematurely changed paid wallet"
            task = _data(
                api.get(f"/v1/admin/provisioning/{request_id}/tasks"),
                "Pending task read failed",
            )[0]
            assert task["installed_revision_id"] is None, (
                "Rejected core falsely acknowledged profile installation"
            )
            uri = _data(
                api.post(
                    f"/v1/admin/network/configurations/profiles/{task['profile_id']}/client-download"
                ),
                "Private profile read failed",
            )["content"].strip()
            link = _data(
                api.post(
                    f"/v1/admin/network/configurations/subscriptions/{subscription_id}/link"
                ),
                "Owned subscription link read failed",
            )["url"]
            _assert_no_delivery(
                customer, scheduler_raw, subscription_id, telegram_id, link
            )
            fail_path = (
                f"/v1/admin/subscriptions/{subscription_id}/provision-failed"
            )
            body = {"reason": "Owned actual-core validation failure"}
            _data(api.post(fail_path, json=body), "Native cancellation failed")
            _data(api.post(fail_path, json=body), "Cancellation replay failed")
            assert (
                _data(api.get(wallet_path), "Wallet reread failed")[
                    "balance_rial"
                ]
                == 200000
            ), "Cancellation refunded before acknowledged absence"
            _data(
                api.put(
                    config_api,
                    json={
                        "expected_revision": broken["revision"],
                        "reason": "Restore topology for original retirement",
                        "document": None,
                    },
                ),
                "Managed topology restoration failed",
            )
            result = exercise_native_failed_purchase_refund(
                scheduler_raw, request_id
            )
            revoked = _data(
                api.get(f"/v1/admin/provisioning/{request_id}/tasks"),
                "Revoked task read failed",
            )[0]
            state = _data(api.get(runtime_path), "Absent runtime read failed")
            assert (
                revoked["state"] == "revoked"
                and revoked["membership_sha256"] is not None
            ), "Refund lacks actual absent membership acknowledgement"
            assert (
                state["observed_status"] == "running"
                and state["applied_revision_id"]
                == revoked["installed_revision_id"]
            ), "Refund lacks installed live replacement bundle"
            runtime.exercise(
                "refunded-original-denied", runtime.client(uri), accepted=False
            )
            _assert_no_delivery(
                customer, scheduler_raw, subscription_id, telegram_id, link
            )
            _data(
                api.post(fail_path, json=body),
                "Completed failure replay failed",
            )
            retry = api.post(
                f"/v1/admin/provisioning/{request_id}/retry",
                json={"reason": "Owned duplicate refund retry"},
            )
            assert retry.status_code == 409, (
                "Refunded work unexpectedly reopened"
            )
            assert (
                _data(api.get(wallet_path), "Refunded wallet read failed")[
                    "balance_rial"
                ]
                == 300000
            ), "Refund replay changed wallet balance"
            ledger = api.get(
                wallet_path + "/entries", params={"reason": "provision_refund"}
            )
            entries = _data(ledger, "Refund ledger read failed")
            assert (
                ledger.json()["meta"]["pager"]["total_items"] == 1
                and len(entries) == 1
                and entries[0]["amount_rial"] == 100000
            ), "Refund was not credited exactly once"
            _stop_core(api, runtime_path, process)
            return result
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)


def _assert_no_delivery(customer, raw, subscription_id, telegram_id, link):
    delivery = _data(
        customer.post(
            f"/v1/bot/subscriptions/{subscription_id}/delivery",
            headers={"X-Papilio-Bot-Key": raw["security"]["bot_service_key"]},
            json={"telegram_id": telegram_id, "display_name": "Owned buyer"},
        ),
        "Failed purchase bot read failed",
    )
    assert delivery["status"] != "active" and delivery["feed_url"] is None, (
        "Failed purchase exposed active delivery"
    )
    path = urlsplit(link).path
    assert customer.get(path).status_code == 404, (
        "Inactive purchased feed remained available"
    )
