"""Owned CLOSED child, unacknowledged paid admission and exact revoke proof.

HTTP decisions use the native application. Original component evidence is never
synthesized. This gate deliberately omits the paid admission ACK; it does not
claim continuous successors or automatic node cancellation orchestration.
"""

import json
import os
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx

from tests.managed_installation_agent import compact, digest
from tests.managed_ip_agent import (
    BoundStockClient,
    EchoTarget,
    InstalledTlsEndpoints,
    UnixHTTP,
    denied,
    launch,
    private_write,
    roundtrip,
    stage_stock,
    stop_owned,
)


@dataclass(frozen=True, slots=True)
class NativePaidRevocationResult:
    window_id: str
    grant_id: int
    epoch: str
    task_id: int
    snapshot_sha256: str
    revocation_sha256: str
    upload_bytes: int
    download_bytes: int
    wallet_balance_rial: int
    refund_count: int
    child_stopped: bool
    replay_unchanged: bool


def data(response):
    assert response.status_code == 200, "native_paid_revoke_api_rejected"
    envelope = response.json()
    assert envelope.get("success") is True, "native_paid_revoke_api_failed"
    return envelope["data"]


def control(root, method, path, payload=None, *, expected=200):
    connection = UnixHTTP(root / "control" / "control.sock")
    try:
        connection.request(
            method,
            path,
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        raw = response.read(131073)
        assert len(raw) <= 131072, "native_paid_revoke_control_capacity"
        assert response.status == expected, (
            "native_paid_revoke_control_rejected"
        )
        return raw, {
            key.lower(): value for key, value in response.getheaders()
        }
    finally:
        connection.close()


def original_receipt(raw, headers, epoch, **identities):
    assert (
        headers.get("x-papilio-receipt-epoch") == epoch
        and headers.get("x-papilio-receipt-sha256") == digest(raw)
        and headers.get("x-papilio-receipt-bytes") == str(len(raw))
        and headers.get("content-length") == str(len(raw))
        and headers.get("cache-control") == "no-store"
    ), "native_paid_revoke_original_headers"
    for suffix, value in identities.items():
        assert headers.get(("X-Papilio-Receipt-" + suffix).lower()) == str(
            value
        ), "native_paid_revoke_original_identity"


def wait_closed(root, process, timeout):
    deadline = time.monotonic() + timeout
    path = root / "managed-agent" / "managed-installation.json"
    while time.monotonic() < deadline:
        assert process.poll() is None, "native_paid_revoke_child_exited"
        if path.exists():
            installation = json.loads(path.read_bytes())
            if installation.get("acceptance"):
                raw, _ = control(root, "GET", "/v1/observe")
                observation = json.loads(raw)
                if all(
                    row["phase"] == "enrolled_closed"
                    for row in observation["profiles"]
                ):
                    ack = installation["acknowledgement"]
                    assert (
                        digest(ack["original_receipt"].encode())
                        == ack["receipt"]["receipt_sha256"]
                    ), "native_paid_revoke_closed_original_changed"
                    return installation
        time.sleep(0.02)
    raise AssertionError("native_paid_revoke_closed_timeout")


def exercise_native_paid_revocation(
    root: Path,
    runtime_binary: Path,
    registry: dict,
    installation_id: int,
    profile_id: int,
    task_id: int,
    subscription: dict,
    api_url: str,
    node: dict,
    admin_headers: dict,
    binaries: Path,
    *,
    payload: bytes,
):
    assert payload and len(payload) * 2 < 1024, (
        "native_paid_revoke_payload_capacity"
    )
    owned_registry = {**registry, "installation_id": installation_id}
    assert not owned_registry.get("window_cycle"), (
        "native_paid_revoke_manual_cycle_required"
    )
    config = {
        "enabled": True,
        "api_url": api_url,
        "node_code": node["node"]["code"],
        "state_directory": str(root / "unused-stock-state"),
        "managed_installation": owned_registry,
        "poll_interval_ms": 300,
        "http_timeout_ms": 15000,
        "max_response_bytes": 2097152,
        "max_idle_connections": 2,
        "page_size": 8,
        "max_pages_per_poll": 2,
    }
    config_path = root / "cancel-agent-config.json"
    private_write(config_path, compact(config))
    command = [str(runtime_binary), "-config", str(config_path)]
    environment = {**os.environ, "PAPILIO_NODE_KEY": node["agent_key"]}
    prefix = "/v1/nodes/" + node["node"]["code"]
    with ExitStack() as stack:
        api = stack.enter_context(
            httpx.Client(
                base_url=api_url,
                headers={"X-Papilio-Node-Key": node["agent_key"]},
                timeout=10,
                trust_env=False,
            )
        )
        admin = stack.enter_context(
            httpx.Client(
                base_url=api_url,
                headers=admin_headers,
                timeout=10,
                trust_env=False,
            )
        )
        stock = stage_stock(
            root, binaries / "xray", binaries.parent / "artifacts.json"
        )
        process = launch(
            command, stack, root / "cancel-agent.log", environment=environment
        )
        installation = wait_closed(root, process, 20)
        issued = data(
            api.post(
                prefix + f"/managed-installations/{installation_id}/windows",
                json={
                    "provision_task_id": task_id,
                    "profile_id": profile_id,
                    "generation": 0,
                    "process_epoch": installation["acceptance"][
                        "process_epoch"
                    ],
                    "request_key": "native-cancel-window-"
                    + str(installation_id),
                    "requested_bytes": 1024,
                },
            )
        )
        assert issued["provision_claim"]["task_id"] == task_id, (
            "native_paid_revoke_task_changed"
        )
        window = issued["window"]
        original_window = issued["original_window"].encode()
        assert (
            digest(original_window) == issued["window_sha256"]
            and json.loads(original_window) == window
        ), "native_paid_revoke_window_changed"
        private_write(root / "cancel-issued.json", compact(issued))
        original, headers = control(
            root, "POST", "/v1/windows/admit-original", original_window
        )
        original_receipt(
            original,
            headers,
            window["epoch"],
            **{"Window-ID": window["window_id"]},
        )
        admission = json.loads(original)
        assert (
            admission["window_sha256"] == issued["window_sha256"]
            and admission["budget_enforced"]
            and admission["deadline_enforced"]
            and admission["historical_only"]
            and not admission["api_authority"]
        ), "native_paid_revoke_admission_invalid"
        assert (
            admission["startup_receipt_sha256"]
            == installation["acknowledgement"]["receipt"]["receipt_sha256"]
        ), "native_paid_revoke_startup_changed"
        private_write(root / "cancel-admission-original.json", original)
        artifact = installation["claim"]["artifact_content"]
        assert (
            digest(artifact.encode())
            == installation["claim"]["expectation"]["artifact_sha256"]
        ), "native_paid_revoke_artifact_changed"
        binding = window["binding"]
        inbound = next(
            row
            for row in json.loads(artifact)["inbounds"]
            if row["tag"] == binding["inbound_tag"]
        )
        credential = next(
            row
            for row in inbound["settings"]["clients"]
            if row["email"] == binding["counter_identity"]
        )
        endpoints = InstalledTlsEndpoints(
            {profile_id: (inbound["port"], credential["id"])},
            Path(registry["certificates"][0]["path"]),
        )
        target = EchoTarget()
        stack.callback(target.close)
        client = BoundStockClient(
            root, stock, endpoints, profile_id, "127.0.0.1", stack
        )
        connection = client.connect(target.port)
        roundtrip(connection, payload)
        connection.close()
        fail_path = (
            f"/v1/admin/subscriptions/{subscription['id']}/provision-failed"
        )
        reason = {
            "reason": "Owned native unacknowledged admission cancellation"
        }
        cancelled = data(admin.post(fail_path, json=reason))
        assert (
            cancelled["status"] == "pending_provision"
            and cancelled["activated_at"] is None
        ), "native_paid_revoke_premature_refund"
        wallet_path = (
            f"/v1/admin/payments/wallets/{subscription['customer_id']}"
        )
        assert data(admin.get(wallet_path))["balance_rial"] == 200000, (
            "native_paid_revoke_unsafe_refund"
        )
        request = {
            "epoch": window["epoch"],
            "request_id": uuid4().hex,
            "barrier_id": uuid4().hex,
            "window_id": window["window_id"],
            "binding": binding,
        }
        revoke_raw, headers = control(
            root, "POST", "/v1/windows/revoke-original", compact(request)
        )
        original_receipt(
            revoke_raw,
            headers,
            window["epoch"],
            **{"Request-ID": request["request_id"], "Profile-ID": profile_id},
        )
        revoked = json.loads(revoke_raw)
        assert (
            revoked["request"] == request
            and revoked["window"] == window
            and revoked["admission_blocked"]
            and revoked["historical_only"]
            and not revoked["api_authority"]
        ), "native_paid_revoke_original_mismatch"
        submission = {
            "original_receipt": revoke_raw.decode(),
            "receipt": {
                "epoch": window["epoch"],
                "request_id": request["request_id"],
                "profile_id": profile_id,
                "receipt_sha256": digest(revoke_raw),
                "bytes": len(revoke_raw),
            },
        }
        private_write(
            root / "cancel-revocation-submission.json", compact(submission)
        )
        fetched, _ = control(
            root, "GET", "/v1/windows/revocations/" + request["request_id"]
        )
        assert fetched == revoke_raw, (
            "native_paid_revoke_original_replay_changed"
        )
        denied(client, target.port)
        control(
            root, "POST", "/v1/windows/admit", original_window, expected=409
        )
        historical, _ = control(
            root, "POST", "/v1/windows/admit-original", original_window
        )
        assert historical == original, (
            "native_paid_revoke_historical_proof_changed"
        )
        raw, _ = control(root, "GET", "/v1/observe")
        assert all(
            row["phase"] == "frozen" for row in json.loads(raw)["profiles"]
        ), "native_paid_revoke_reopened"
        revocation_path = (
            prefix + "/managed-windows/" + window["window_id"] + "/revocation"
        )
        assert api.post(revocation_path, json=submission).status_code == 409, (
            "native_paid_revoke_without_finality_accepted"
        )
        assert data(admin.get(wallet_path))["balance_rial"] == 200000, (
            "native_paid_revoke_before_finality_refund"
        )
        snapshot_raw, snapshot_headers = control(
            root,
            "GET",
            "/v1/windows/snapshots/" + revoked["snapshot"]["barrier_id"],
        )
        original_receipt(
            snapshot_raw,
            snapshot_headers,
            window["epoch"],
            **{"Barrier-ID": revoked["snapshot"]["barrier_id"]},
        )
        assert (
            digest(snapshot_raw) == revoked["snapshot"]["snapshot_sha256"]
        ), "native_paid_revoke_final_snapshot_changed"
        final_submission = {
            "original_receipt": snapshot_raw.decode(),
            "receipt": revoked["snapshot"],
        }
        private_write(
            root / "cancel-final-submission.json", compact(final_submission)
        )
        final_path = (
            prefix + "/managed-windows/" + window["window_id"] + "/finalize"
        )
        finality = data(api.post(final_path, json=final_submission))
        assert finality["upload_bytes"] == len(payload) and finality[
            "download_bytes"
        ] == len(payload), "native_paid_revoke_payload_finality"
        assert data(admin.get(wallet_path))["balance_rial"] == 200000, (
            "native_paid_revoke_finality_alone_refunded"
        )
        with ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(api.post, revocation_path, json=submission)
            second = workers.submit(api.post, revocation_path, json=submission)
            results = (
                data(first.result(timeout=15)),
                data(second.result(timeout=15)),
            )
        assert (
            results[0]
            == results[1]
            == data(api.post(revocation_path, json=submission))
        ), "native_paid_revoke_concurrent_replay_changed"
        assert results[0]["provision_task_id"] == task_id and results[0][
            "revocation_sha256"
        ] == digest(revoke_raw), "native_paid_revoke_acceptance_changed"
        assert data(api.post(final_path, json=final_submission)) == finality, (
            "native_paid_revoke_finality_replay_changed"
        )
        data(admin.post(fail_path, json=reason))
        assert data(admin.get(wallet_path))["balance_rial"] == 300000, (
            "native_paid_revoke_refund_missing"
        )
        entries_response = admin.get(
            wallet_path + "/entries", params={"reason": "provision_refund"}
        )
        entries = data(entries_response)
        assert (
            entries_response.json()["meta"]["pager"]["total_items"] == 1
            and len(entries) == 1
            and entries[0]["amount_rial"] == 100000
        ), "native_paid_revoke_duplicate_refund"
        installation_path = (
            root / "managed-agent" / "managed-installation.json"
        )
        settings_path = root / "managed-agent" / "managed-settings.json"
        before = installation_path.read_bytes()
        identity = (
            settings_path.stat().st_ino,
            settings_path.stat().st_mtime_ns,
        )
        stop_owned(process)
        assert not (root / "control" / "control.sock").exists(), (
            "native_paid_revoke_socket_not_stopped"
        )
        replay = launch(
            command + ["-once"],
            stack,
            root / "cancel-replay.log",
            environment=environment,
        )
        assert replay.wait(timeout=10) == 0, (
            "native_paid_revoke_historical_recovery_failed"
        )
        unchanged = (
            installation_path.read_bytes() == before
            and identity
            == (settings_path.stat().st_ino, settings_path.stat().st_mtime_ns)
            and not (root / "control" / "control.sock").exists()
        )
        with socket.socket() as check:
            check.settimeout(0.1)
            stopped = check.connect_ex(("127.0.0.1", inbound["port"])) != 0
        assert unchanged and stopped, "native_paid_revoke_replay_relaunched"
        return NativePaidRevocationResult(
            window["window_id"],
            window["grant_id"],
            window["epoch"],
            task_id,
            digest(snapshot_raw),
            digest(revoke_raw),
            finality["upload_bytes"],
            finality["download_bytes"],
            300000,
            1,
            stopped,
            unchanged,
        )
