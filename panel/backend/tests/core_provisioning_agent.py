"""Native paid-purchase acceptance with an owned Go daemon and actual cores."""

import base64
import json
import os
import signal
import subprocess
import time
from urllib.parse import urlsplit

import httpx

from tests.scheduler_runtime import exercise_native_installed_purchase


def exercise_installed_purchase(
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
    config = {
        "enabled": True,
        "api_url": base_url,
        "node_code": node["node"]["code"],
        "state_directory": str(directory / "installed-journal"),
        "binaries": {
            "xray": str(binaries / "xray"),
            "sing_box": str(binaries / "sing-box"),
        },
        "poll_interval_ms": 50,
        "http_timeout_ms": 5000,
        "max_response_bytes": 2097152,
        "max_idle_connections": 4,
        "page_size": 16,
        "max_pages_per_poll": 4,
        "max_artifacts": 16,
        "max_artifact_bytes": 1048576,
        "max_bundle_bytes": 2097152,
        "max_journal_bytes": 1048576,
        "max_receipts": 32,
        "max_cores": 4,
        "validation_timeout_ms": 5000,
        "startup_grace_ms": 150,
        "stop_timeout_ms": 2000,
        "max_processes": 4,
        "provisioning": {
            "mode": "installed_only",
            "max_memberships": 16,
            "max_receipts": 32,
            "page_size": 16,
            "max_pages_per_core": 4,
            "max_tasks_per_poll": 32,
        },
    }
    path = directory / "installed-agent.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    log_path = directory / "installed-agent.log"
    base = f"/v1/admin/network/cores/{core['id']}/runtime"
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
            result = exercise_native_installed_purchase(
                scheduler_raw, request_id
            )
            assert process.poll() is None, "Owned runtime agent exited"
            fresh = _data(
                api.get(f"/v1/admin/subscriptions/{subscription_id}"),
                "Subscription read failed",
            )
            assert fresh["status"] == "active", "Purchase remained inactive"
            tasks = _data(
                api.get(f"/v1/admin/provisioning/{request_id}/tasks"),
                "Provisioning task read failed",
            )
            assert len(tasks) == 1, "Unexpected purchased profile count"
            task = tasks[0]
            state = _data(api.get(base), "Runtime state read failed")
            assert (
                task["state"] == "applied"
                and task["installed_revision_id"]
                == state["applied_revision_id"]
                and task["installed_revision_id"] is not None
                and task["membership_sha256"] is not None
                and state["observed_status"] == "running"
            ), "Profile ACK lacks committed live installation proof"
            delivery = _data(
                customer.post(
                    f"/v1/bot/subscriptions/{subscription_id}/delivery",
                    headers={
                        "X-Papilio-Bot-Key": scheduler_raw["security"][
                            "bot_service_key"
                        ]
                    },
                    json={
                        "telegram_id": telegram_id,
                        "display_name": "Owned buyer",
                    },
                ),
                "Owning bot delivery failed",
            )
            assert (
                delivery["status"] == "active"
                and delivery["subscription_id"] == subscription_id
                and delivery["feed_url"]
            ), "Active purchase has no bot delivery"
            parsed = urlsplit(delivery["feed_url"])
            feed_path = parsed.path
            if parsed.query:
                feed_path += "?" + parsed.query
            feed = customer.get(feed_path)
            assert feed.status_code == 200, "Customer feed failed"
            download = _data(
                api.post(
                    "/v1/admin/network/configurations/profiles/"
                    f"{task['profile_id']}/client-download"
                ),
                "Installed client download failed",
            )
            uri = download["content"].strip()
            assert uri.startswith("vless://"), "Unexpected client protocol"
            content = feed.text.strip()
            if not content.startswith("vless://"):
                content = base64.b64decode(content, validate=True).decode()
            outbound = runtime.client(uri)
            assert any(
                runtime.client(entry) == outbound
                for entry in content.splitlines()
            ), "Customer feed does not contain purchased configuration"
            public_profiles = _data(
                customer.get(parsed.path + "/profiles"),
                "Owning customer profile list failed",
            )
            public_profile = next(
                row
                for row in public_profiles
                if row["profile_id"] == task["profile_id"]
            )
            public_download = _data(
                customer.get(
                    parsed.path + f"/profiles/{task['profile_id']}/download",
                    params={"host_id": public_profile["host_id"]},
                ),
                "Owning customer configuration download failed",
            )
            assert runtime.client(public_download["content"].strip()) == (
                outbound
            ), "Customer download differs from installed credentials"
            runtime.exercise("paid-installed-valid", outbound, accepted=True)
            outbound["uuid"] = "00000000-0000-0000-0000-000000000000"
            runtime.exercise(
                "paid-installed-invalid", outbound, accepted=False
            )
            _stop_core(api, base, process)
            return result
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)


def _data(response, message):
    assert response.status_code == 200, message
    return response.json()["data"]


def _stop_core(api, base, process):
    state = _data(api.get(base), "Runtime cleanup read failed")
    command = _data(
        api.post(
            base + "/commands",
            json={
                "expected_revision": state["revision"],
                "action": "stop",
                "request_key": "installed_cleanup_" + str(time.monotonic_ns()),
                "reason": "Owned purchase acceptance cleanup",
            },
        ),
        "Runtime cleanup command failed",
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        assert process.poll() is None, "Owned runtime exited during cleanup"
        rows = _data(
            api.get(base + "/commands", params={"per_page": 16}),
            "Runtime cleanup command read failed",
        )
        completed = next(row for row in rows if row["id"] == command["id"])
        if completed["state"] in {"succeeded", "failed"}:
            assert completed["state"] == "succeeded", (
                "Owned runtime stop failed"
            )
            final = _data(api.get(base), "Final runtime state read failed")
            assert final["observed_status"] == "stopped", (
                "Owned runtime did not report stopped"
            )
            assert final["automation_paused"] is True, (
                "Explicit operator stop did not pause automation"
            )
            return
        time.sleep(0.05)
    raise AssertionError("Owned runtime stop deadline exceeded")
