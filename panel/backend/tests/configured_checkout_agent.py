"""Actual configured checkout through native workers and owned Go/core."""

import base64
import json
import os
import signal
import subprocess
from urllib.parse import urlsplit

import httpx

from tests.core_provisioning_agent import _data, _stop_core
from tests.scheduler_runtime import _exercise_native_runtime


def exercise_configured_checkout(
    directory,
    binary,
    base_url,
    admin_headers,
    node,
    core,
    runtime,
    scheduler_raw,
    owned_namespace,
    checkout_id,
    identity,
    request_body,
    configuration_ids,
    expected_wallet_rial,
    agent_config,
):
    path = directory / "configured-checkout-agent.json"
    path.write_text(json.dumps(agent_config))
    path.chmod(0o600)
    log_path = directory / "configured-checkout-agent.log"
    bot_headers = {
        "X-Papilio-Bot-Key": scheduler_raw["security"]["bot_service_key"]
    }
    count = len(configuration_ids)
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
        process = subprocess.Popen(
            [str(binary), "-config", str(path)],
            env={**os.environ, "PAPILIO_NODE_KEY": node["agent_key"]},
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        try:
            native = _exercise_native_runtime(
                scheduler_raw,
                "SELECT i.state checkout_state,s.status subscription_status,"
                "r.state request_state,r.generation,i.subscription_id,"
                "r.id request_id,w.balance_rial,COUNT(t.id) task_count,"
                "SUM(t.state='applied' AND "
                "t.installed_revision_id IS NOT NULL AND "
                "t.membership_sha256 IS NOT NULL AND "
                "p.applied_generation=r.generation) proved_count,"
                "(SELECT COUNT(*) FROM tbl_wallet_entries e "
                "WHERE e.wallet_id=w.id AND e.reason='purchase') debit_count "
                "FROM tbl_checkout_intents i "
                "JOIN tbl_subscriptions s ON s.id=i.subscription_id "
                "JOIN tbl_provision_requests r ON r.subscription_id=s.id "
                "JOIN tbl_provision_tasks t ON t.request_id=r.id "
                "JOIN tbl_profiles p ON p.id=t.profile_id "
                "JOIN tbl_wallets w ON w.customer_id=i.customer_id "
                "WHERE i.id=%s GROUP BY i.state,s.status,r.state,r.generation,"
                "i.subscription_id,r.id,w.id,w.balance_rial",
                (checkout_id,),
                lambda row: (
                    row["checkout_state"] == "purchased"
                    and row["subscription_status"] == "active"
                    and row["request_state"] == "active"
                    and row["task_count"] == count
                    and row["proved_count"] == count
                    and row["debit_count"] == 1
                    and row["balance_rial"] == expected_wallet_rial
                ),
                (
                    "subscription_id",
                    "request_id",
                    "generation",
                    "task_count",
                    "debit_count",
                    "balance_rial",
                ),
                (
                    "ScanCheckouts",
                    "RecoverCheckout",
                    "ScanProvisioning",
                    "ScanCoreProvisioning",
                    "EnsureCoreProvisioning",
                ),
                owned_namespace=owned_namespace,
            )
            assert process.poll() is None, "Owned checkout agent exited"
            subscription_id, request_id, generation = native[:3]
            checkout = _data(
                customer.post(
                    f"/v1/bot/checkouts/{checkout_id}/status",
                    headers=bot_headers,
                    json=identity,
                ),
                "Owning configured checkout read failed",
            )
            assert (
                checkout["state"] == "purchased"
                and checkout["delivery_mode"] == "configured_bundle"
                and checkout["subscription_id"] == subscription_id
            ), "Configured checkout lacks its owning purchased subscription"
            foreign = customer.post(
                f"/v1/bot/checkouts/{checkout_id}/status",
                headers=bot_headers,
                json={**identity, "telegram_id": identity["telegram_id"] + 1},
            )
            assert foreign.status_code == 404, (
                "Foreign checkout owner admitted"
            )
            base = f"/v1/admin/network/cores/{core['id']}/runtime"
            state = _data(api.get(base), "Installed checkout core read failed")
            tasks = _data(
                api.get(f"/v1/admin/provisioning/{request_id}/tasks"),
                "Configured checkout profile tasks unavailable",
            )
            assert len(tasks) == count
            assert {row["configuration_id"] for row in tasks} == set(
                configuration_ids
            ), "Purchased bundle membership changed"
            assert all(
                row["state"] == "applied"
                and row["request_id"] == request_id
                and row["installed_revision_id"]
                == state["applied_revision_id"]
                and row["installed_revision_id"] is not None
                and row["membership_sha256"] is not None
                for row in tasks
            ), "A profile lacks independent live installed membership proof"
            assert state["observed_status"] == "running"
            requests = api.get(
                "/v1/admin/provisioning",
                params={"subscription_id": subscription_id},
            )
            request_rows = _data(requests, "Native generation read failed")
            assert any(
                row["id"] == request_id and row["generation"] == generation
                for row in request_rows
            ), "Installed task generation differs from owning request"
            delivery = _data(
                customer.post(
                    f"/v1/bot/subscriptions/{subscription_id}/delivery",
                    headers=bot_headers,
                    json=identity,
                ),
                "Owning configured-bundle delivery unavailable",
            )
            assert (
                delivery["subscription_id"] == subscription_id
                and delivery["status"] == "active"
            )
            parsed = urlsplit(delivery["feed_url"])
            feed_path = parsed.path + (
                "?" + parsed.query if parsed.query else ""
            )
            feed = customer.get(feed_path)
            assert feed.status_code == 200, "Configured feed unavailable"
            content = feed.text.strip()
            if not content.startswith("vless://"):
                content = base64.b64decode(content, validate=True).decode()
            outbounds = [runtime.client(uri) for uri in content.splitlines()]
            assert len(outbounds) == count, "Configured feed bundle incomplete"
            profiles = _data(
                customer.get(parsed.path + "/profiles"),
                "Owning configured-bundle profiles unavailable",
            )
            assert {row["profile_id"] for row in profiles} == {
                row["profile_id"] for row in tasks
            }
            for index, task in enumerate(tasks):
                public_profile = next(
                    row
                    for row in profiles
                    if row["profile_id"] == task["profile_id"]
                )
                downloaded = _data(
                    customer.get(
                        parsed.path
                        + f"/profiles/{task['profile_id']}/download",
                        params={"host_id": public_profile["host_id"]},
                    ),
                    "Owning configured-bundle download failed",
                )
                outbound = runtime.client(downloaded["content"].strip())
                assert outbound in outbounds, "Download absent from paid feed"
                runtime.exercise(
                    f"configured-checkout-{index}-valid",
                    outbound,
                    accepted=True,
                )
                wrong = {
                    **outbound,
                    "uuid": "00000000-0000-0000-0000-000000000000",
                }
                runtime.exercise(
                    f"configured-checkout-{index}-invalid",
                    wrong,
                    accepted=False,
                )
            replay = _data(
                customer.post(
                    "/v1/bot/checkouts",
                    headers=bot_headers,
                    json={**identity, **request_body},
                ),
                "Owning configured checkout replay failed",
            )
            assert (
                replay["id"] == checkout_id
                and replay["subscription_id"] == subscription_id
                and replay["state"] == "purchased"
            ), "Configured checkout replay duplicated fulfillment"
            conflict = customer.post(
                "/v1/bot/checkouts",
                headers=bot_headers,
                json={**identity, **request_body, "auto_renew": False},
            )
            assert conflict.status_code == 409, "Changed request was replayed"
            wallet = _data(
                api.get(
                    f"/v1/admin/payments/wallets/{checkout['customer_id']}"
                ),
                "Configured checkout wallet read failed",
            )
            assert wallet["balance_rial"] == expected_wallet_rial, (
                "Configured checkout replay charged twice"
            )
            _stop_core(api, base, process)
            return native
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
