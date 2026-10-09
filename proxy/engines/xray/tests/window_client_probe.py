"""Actual isolated CLOSED/local-window stock TLS/Reality lifecycle.

No API, settled-payment, byte-budget or deadline authority is exercised here.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import signal
import socket
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import barrier_probe
from barrier_probe import Core, UnixHTTP, Upstream, digest, encoded
from stock_client_probe import (
    SecurityFixture,
    StockClient,
    roundtrip,
    stage_stock,
)

ALLOWED_FAILURE_CODES = frozenset(
    (
        "B-window-closed-by-A",
        "admission_identity_changed",
        "aggregate_budget_not_exact",
        "automatic_freeze_not_durable",
        "automatic_reason_wrong",
        "automatic_receipt_hash_changed",
        "automatic_receipt_not_replayed",
        "both_sessions_known_upload_missing",
        "contention_claimed_exhaustion",
        "expiry_minted_full_budget",
        "fallback_cleanup",
        "first_window_counter_truth",
        "frozen_window_operations_remain",
        "idle_reserved_read_not_observed",
        "immutable_baseline_lost",
        "initial_profile_not_closed",
        "live_admission_replay_changed",
        "local_admission_rejected",
        "local_predecessor_rejected",
        "local_window_freeze_not_durable",
        "lost_window_receipt_changed",
        "lost_window_response_not_replayed",
        "manual_final_reason_wrong",
        "metadata_claimed_enforcement",
        "next_window_replay_changed",
        "old_acceptance_replay_changed",
        "old_action_closed_strict_replacement",
        "old_receipt_replay_changed",
        "old_window_target_closed_new_window",
        "owned_controlled_outbound_socket_missing",
        "persisted_window_binding_changed",
        "second_window_cumulative_counter_truth",
        "sink_counted_delivery",
        "stock_known_payload",
        "stock_listener_survived",
        "stock_socks_address",
        "stock_socks_destination",
        "stock_socks_negotiation",
        "strict_changed_policy_admitted",
        "strict_final_budget_truth",
        "strict_final_operations_not_joined",
        "strict_first_flush_payload_wrong",
        "strict_old_receipt_changed",
        "strict_predecessor_rejected",
        "unadmitted_prefix_remainder_evidence_missing",
    )
)
ALLOWED_FAILURE_CODES |= frozenset(
    (
        "closed_startup_response",
        "closed_startup_cache",
        "closed_startup_epoch",
        "closed_startup_digest",
        "closed_startup_size",
        "closed_startup_cli_pointer",
        "closed_startup_persisted_bytes",
        "closed_startup_identity",
        "closed_startup_installation",
        "closed_startup_pinned_build",
        "closed_startup_scope",
        "closed_startup_policy",
        "closed_startup_authority",
        "closed_startup_utc6",
        "closed_startup_actual_time",
        "closed_startup_complete_closed_profiles",
        "closed_startup_initial_replay",
        "closed_startup_live_replay_changed",
    )
)

STRICT_DIAGNOSTIC: dict[str, Any] = {}

CURRENT_STAGE = "setup"


def denied(
    client: StockClient, target: int, connection: socket.socket | None = None
) -> None:
    try:
        connection = (
            client.connect(target) if connection is None else connection
        )
        roundtrip(connection, b"closed-local-window-must-not-deliver")
    except (OSError, EOFError):
        return
    raise AssertionError("closed_window_delivered_payload")


class WindowFixture:
    def __init__(self, mode: str, strict: bool = False) -> None:
        self.strict = strict
        self.security = SecurityFixture(mode)
        self.bindings: list[dict[str, Any]] = []
        self.installation: dict[str, str] = {}

    def configure(self, settings: dict[str, Any]) -> None:
        self.security.configure(settings)
        document = settings["document"]
        # Explicit LOCAL membership derived from the exact installed document.
        # This is not the backend NodeClientCredentials digest or an API ACK.
        artifact_sha = digest(encoded(document))
        members: list[dict[str, Any]] = []
        inbound = document["inbounds"][0]
        clients = {
            client["email"]: client
            for client in inbound["settings"]["clients"]
        }
        for binding in settings["bindings"]:
            client = clients[binding["counter_identity"]]
            assert (
                binding["inbound_tag"] == inbound["tag"]
                and client["flow"] == ""
            )
            member = {
                "scope": "local_component_document_membership",
                "binding": binding,
                "credential_sha256": digest(
                    encoded(
                        {
                            "id": client["id"],
                            "flow": client["flow"],
                            "level": client["level"],
                        }
                    )
                ),
                "artifact_filename": "managed-local.json",
                "artifact_sha256": artifact_sha,
            }
            members.append(member)
        membership_sha = digest(encoded(members))
        self.bindings = [
            {
                "binding": member["binding"],
                "membership_sha256": membership_sha,
                "profile_sha256": digest(encoded(member)),
            }
            for member in members
        ]
        settings["accounting_mode"] = "window_component"
        settings["window_policy"] = {
            "max_windows": 8,
            "max_records": 16,
            "max_record_bytes": 16384,
            "max_validity_ms": 120000,
            "transaction_timeout_ms": 5000,
        }
        settings["window_bindings"] = self.bindings
        self.window_policy_sha = digest(
            json.dumps(
                settings["window_policy"],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )
        if self.strict:
            settings["enforcement_policy"] = {
                "max_read_reservation_bytes": 16,
                "max_residual_bytes": 65536,
                "max_concurrent_reservations": 8,
                "read_lease_ms": 10000,
                "reservation_wait_ms": 400,
                "max_clock_skew_ms": 1000,
                "contention_mode": "close_profile",
            }
            self.enforcement_sha = digest(
                json.dumps(
                    settings["enforcement_policy"],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            )
        # Core recomputes exact document/material hashes after this transform.
        self.installation = settings["installation"]

    def grant(
        self,
        core: Core,
        profile: int,
        grant_id: int,
        baseline: tuple[int, int] = (0, 0),
        predecessor: dict[str, Any] | None = None,
        budget: int = 1000000,
        validity: float = 90,
    ) -> dict[str, Any]:
        bound = next(
            item
            for item in self.bindings
            if item["binding"]["profile_id"] == profile
        )
        issued = dt.datetime.now(dt.timezone.utc)

        def stamp(value: dt.datetime) -> str:
            return value.isoformat(timespec="microseconds").replace(
                "+00:00", "Z"
            )

        grant = {
            "grant_id": grant_id,
            "window_id": uuid.uuid4().hex,
            "epoch": core.epoch,
            "installation": dict(self.installation),
            **bound,
            "baseline_upload_bytes": baseline[0],
            "baseline_download_bytes": baseline[1],
            "allocated_bytes": budget,
            "issued_at": stamp(issued),
            "valid_until": stamp(issued + dt.timedelta(seconds=validity)),
            "predecessor": predecessor,
        }
        if self.strict:
            grant.update(
                enforcement_mode="strict_decoded",
                enforcement_sha256=self.enforcement_sha,
            )
        return grant

    def close(self) -> None:
        self.security.close()


def admitted(core: Core, grant: dict[str, Any]) -> dict[str, Any]:
    status, result = core.request("POST", "/v1/windows/admit", grant)
    assert (
        status == 200 and result["state"] == "local_component_window_admitted"
    ), "local_admission_rejected"
    assert (
        result["budget_enforced"] is False
        and result["deadline_enforced"] is False
    ), "metadata_claimed_enforcement"
    assert result["window"] == grant, "admission_identity_changed"
    return result


def freeze_lost_response(
    core: Core, window: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    barrier = uuid.uuid4().hex
    body = {
        "epoch": core.epoch,
        "barrier_id": barrier,
        "windows": [
            {
                "profile_id": window["binding"]["profile_id"],
                "window_id": window["window_id"],
            }
        ],
    }
    payload = encoded(body)
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(3)
        connection.connect(str(core.journal / "control.sock"))
        header = (
            b"POST /v1/windows/freeze HTTP/1.1\r\nHost: localhost\r\n"
            b"Content-Type: application/json\r\nContent-Length: "
            + str(len(payload)).encode()
            + b"\r\nConnection: close\r\n\r\n"
        )
        connection.sendall(header + payload)
        # Actual request, deliberate response loss; no final response consumed.
    intent = core.journal / f"{barrier}.intent"
    snapshot = core.journal / f"{barrier}.json"
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        if intent.is_file() and snapshot.is_file():
            break
        time.sleep(0.02)
    assert intent.is_file() and snapshot.is_file(), (
        "local_window_freeze_not_durable"
    )
    persisted = json.loads(snapshot.read_bytes())
    assert persisted["windows"] == [window], "persisted_window_binding_changed"
    status, replay = core.request("POST", "/v1/windows/freeze", body)
    assert status == 200 and replay["state"] == "durable_prototype_snapshot", (
        "lost_window_response_not_replayed"
    )
    assert replay["snapshot"] == persisted and replay["receipt"][
        "snapshot_sha256"
    ] == digest(snapshot.read_bytes()), "lost_window_receipt_changed"
    return body, replay


def closed_startup_bytes(core: Core) -> tuple[bytes, dict[str, str]]:
    connection = UnixHTTP(core.journal / "control.sock")
    try:
        connection.request("GET", "/v1/startup-closed")
        response = connection.getresponse()
        payload = response.read(131073)
        assert response.status == 200 and 0 < len(payload) <= 131072, (
            "closed_startup_response"
        )
        headers = {
            name.lower(): value for name, value in response.getheaders()
        }
        assert (
            headers.get("content-type") == "application/json"
            and headers.get("cache-control") == "no-store"
        ), "closed_startup_cache"
        assert headers.get("x-papilio-receipt-epoch") == core.epoch, (
            "closed_startup_epoch"
        )
        assert headers.get("x-papilio-receipt-sha256") == digest(payload), (
            "closed_startup_digest"
        )
        assert headers.get("content-length") == str(len(payload)), (
            "closed_startup_size"
        )
        return payload, headers
    finally:
        connection.close()


def verify_closed_startup(
    core: Core, fixture: WindowFixture, started: dt.datetime
) -> bytes:
    payload, _ = closed_startup_bytes(core)
    receipt = core.closed_startup_receipt
    assert receipt == {
        "epoch": core.epoch,
        "receipt_sha256": digest(payload),
        "bytes": len(payload),
    }, "closed_startup_cli_pointer"
    persisted = core.journal / "closed-startup.json"
    assert (
        persisted.is_file()
        and persisted.stat().st_mode & 0o077 == 0
        and persisted.read_bytes() == payload
    ), "closed_startup_persisted_bytes"
    evidence = json.loads(payload)
    assert (
        evidence["state"] == "isolated_closed_startup_observation"
        and evidence["epoch"] == core.epoch
    ), "closed_startup_identity"
    assert evidence["installation"] == fixture.installation, (
        "closed_startup_installation"
    )
    assert (
        evidence["adapter_revision"] == 1
        and evidence["source_commit"]
        == "d2758a023cd7f4174a5a5fa4ff66e487d4342ba0"
        and evidence["module"] == "github.com/xtls/xray-core@v1.260327.0"
    ), "closed_startup_pinned_build"
    assert (
        evidence["accounting_scope"] == "decoded_managed_tcp_payload_admission"
        and evidence["accounting_mode"] == "window_component"
        and evidence["enforcement_mode"] == "strict_decoded"
    ), "closed_startup_scope"
    assert (
        evidence["enforcement_sha256"] == fixture.enforcement_sha
        and evidence["window_policy_sha256"] == fixture.window_policy_sha
    ), "closed_startup_policy"
    assert evidence["historical_only"] is True and all(
        evidence[name] is False
        for name in ("api_authority", "budget_enforced", "deadline_enforced")
    ), "closed_startup_authority"
    stamp = evidence["observed_at"]
    assert isinstance(stamp, str) and re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", stamp
    ), "closed_startup_utc6"
    observed = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    assert started <= observed <= dt.datetime.now(dt.timezone.utc), (
        "closed_startup_actual_time"
    )
    expected = [
        {
            **bound,
            "phase": "enrolled_closed",
            "active_operations": 0,
            "resources": 0,
            "upload_bytes": 0,
            "download_bytes": 0,
            "unadmitted_upload_bytes": 0,
            "unadmitted_download_bytes": 0,
        }
        for bound in sorted(
            fixture.bindings, key=lambda item: item["binding"]["profile_id"]
        )
    ]
    assert evidence["profiles"] == expected, (
        "closed_startup_complete_closed_profiles"
    )
    assert closed_startup_bytes(core)[0] == payload, (
        "closed_startup_initial_replay"
    )
    return payload


def verify_startup_replay(core: Core, payload: bytes) -> None:
    assert (
        closed_startup_bytes(core)[0] == payload
        and (core.journal / "closed-startup.json").read_bytes() == payload
    ), "closed_startup_live_replay_changed"


def exercise(
    binary: Path, stock: Path, root: Path, mode: str, strict: bool = False
) -> None:
    global CURRENT_STAGE
    CURRENT_STAGE = "setup"
    fixture = WindowFixture(mode, strict)
    upstream = Upstream("echo")
    core: Core | None = None
    clients: list[StockClient] = []
    extra_upstreams: list[Upstream] = []
    try:
        started = dt.datetime.now(dt.timezone.utc)
        core = Core(binary, root, fixture.configure)
        CURRENT_STAGE = "closed_startup_observation"
        startup = (
            verify_closed_startup(core, fixture, started) if strict else None
        )
        CURRENT_STAGE = "initial_closed"
        assert all(
            core.profile(number)["phase"] == "enrolled_closed"
            for number in (1, 2)
        ), "initial_profile_not_closed"
        for number in (1, 2):
            clients.append(
                StockClient(
                    stock,
                    core,
                    number,
                    mode,
                    fixture.security.public_key,
                    fixture.security.short_id,
                )
            )
        for client in clients:
            denied(client, upstream.port)
        CURRENT_STAGE = "local_admission"
        first, other = fixture.grant(core, 1, 1), fixture.grant(core, 2, 2)
        first_ack, b_ack = admitted(core, first), admitted(core, other)
        assert (
            admitted(core, first) == first_ack
            and admitted(core, other) == b_ack
        ), "live_admission_replay_changed"
        CURRENT_STAGE = "first_known_traffic"
        a, b = (client.connect(upstream.port) for client in clients)
        payload_a, payload_b = (
            b"window-owned-A-first",
            b"window-owned-B-persistent",
        )
        roundtrip(a, payload_a)
        roundtrip(b, payload_b)
        if startup is not None:
            verify_startup_replay(core, startup)
        CURRENT_STAGE = "first_freeze_response_loss"
        body, frozen = freeze_lost_response(core, first)
        totals = frozen["snapshot"]["profiles"][0]
        assert totals["upload_bytes"] == len(payload_a) and totals[
            "download_bytes"
        ] == len(payload_a), "first_window_counter_truth"
        assert core.profile(1)["active_operations"] == 0, (
            "frozen_window_operations_remain"
        )
        denied(clients[0], upstream.port, a)
        denied(clients[0], upstream.port)
        roundtrip(b, b"B-live-while-A-frozen")
        CURRENT_STAGE = "local_predecessor_acceptance"
        acceptance = {
            "acceptance_id": uuid.uuid4().hex,
            "epoch": core.epoch,
            "profile_id": 1,
            "barrier_id": body["barrier_id"],
            "snapshot_sha256": frozen["receipt"]["snapshot_sha256"],
        }
        status, accepted = core.request(
            "POST", "/v1/windows/accept-predecessor", acceptance
        )
        assert (
            status == 200
            and accepted["state"] == "local_component_predecessor_accepted"
        ), "local_predecessor_rejected"
        CURRENT_STAGE = "new_window_same_B_session"
        next_window = fixture.grant(
            core,
            1,
            3,
            (totals["upload_bytes"], totals["download_bytes"]),
            acceptance,
        )
        next_ack = admitted(core, next_window)
        fresh = clients[0].connect(upstream.port)
        next_payload = b"window-owned-A-reopened"
        roundtrip(fresh, next_payload)
        denied(clients[0], upstream.port, a)
        roundtrip(b, b"B-same-session-after-A-reopen")
        CURRENT_STAGE = "immutable_old_action_replays"
        status, old_receipt = core.request("POST", "/v1/windows/freeze", body)
        assert status == 200 and old_receipt == frozen, (
            "old_receipt_replay_changed"
        )
        status, old_acceptance = core.request(
            "POST", "/v1/windows/accept-predecessor", acceptance
        )
        assert status == 200 and old_acceptance == accepted, (
            "old_acceptance_replay_changed"
        )
        assert admitted(core, next_window) == next_ack, (
            "next_window_replay_changed"
        )
        delayed = {**body, "barrier_id": uuid.uuid4().hex}
        status, _ = core.request("POST", "/v1/windows/freeze", delayed)
        assert status == 409, "old_window_target_closed_new_window"
        roundtrip(fresh, b"A-still-live-after-old-replays")
        roundtrip(b, b"B-still-same-session-after-replays")
        CURRENT_STAGE = "second_freeze_truthful_baseline"
        second_body, second_frozen = freeze_lost_response(core, next_window)
        second_totals = second_frozen["snapshot"]["profiles"][0]
        expected_a = (
            len(payload_a)
            + len(next_payload)
            + len(b"A-still-live-after-old-replays")
        )
        assert (
            second_totals["upload_bytes"] == expected_a
            and second_totals["download_bytes"] == expected_a
        ), "second_window_cumulative_counter_truth"
        assert second_frozen["snapshot"]["windows"][0][
            "baseline_upload_bytes"
        ] == len(payload_a), "immutable_baseline_lost"
        roundtrip(b, b"B-live-after-second-A-freeze")
        assert core.profile(2)["phase"] == "open", "B-window-closed-by-A"
        # Repeating final receipt for window2 does not mutate any B operation.
        status, second_replay = core.request(
            "POST", "/v1/windows/freeze", second_body
        )
        assert status == 200 and second_replay == second_frozen
        if strict:
            sink, burst, contention = (
                Upstream("no_read"),
                Upstream("no_read"),
                Upstream("no_read"),
            )
            extra_upstreams.extend((sink, burst, contention))
            exercise_strict_windows(
                core,
                fixture,
                clients,
                b,
                upstream,
                sink,
                burst,
                contention,
                second_body,
                second_frozen,
            )
            assert startup is not None
            verify_startup_replay(core, startup)
    finally:
        for client in clients:
            client.close()
        if core is not None:
            core.close()
        upstream.close()
        for target in extra_upstreams:
            target.close()
        fixture.close()


def automatic_receipt(
    core: Core, window: dict[str, Any], reason: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    barrier = digest(f"{core.epoch}:{window['window_id']}:{reason}".encode())[
        :32
    ]
    body = {
        "epoch": core.epoch,
        "barrier_id": barrier,
        "windows": [{"profile_id": 1, "window_id": window["window_id"]}],
    }
    path = core.journal / f"{barrier}.json"
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        if path.is_file():
            break
        time.sleep(0.02)
    if not path.is_file():
        profile = core.profile(1)
        reasons: list[str] = []
        for candidate in list(core.journal.glob("*.json"))[:8]:
            if candidate.stat().st_size > 131072:
                continue
            recorded = json.loads(candidate.read_bytes())
            for evidence in recorded.get("enforcement", []):
                if evidence["window_id"] == window["window_id"]:
                    reasons.append(evidence["closure_reason"])
        STRICT_DIAGNOSTIC.update(
            budget=profile.get("budget"),
            resources=profile.get("resources"),
            automatic_error=profile.get("automatic_freeze_error"),
            phase=profile["phase"],
            delta_upload=profile["totals"]["upload_bytes"]
            - window["baseline_upload_bytes"],
            delta_download=profile["totals"]["download_bytes"]
            - window["baseline_download_bytes"],
            active_operations=profile["active_operations"],
            operation_kinds=profile["operation_kinds"],
            durable_reasons=reasons,
            expected_intent_present=(
                core.journal / f"{barrier}.intent"
            ).is_file(),
        )
    assert path.is_file() and (core.journal / f"{barrier}.intent").is_file(), (
        "automatic_freeze_not_durable"
    )
    status, result = core.request("POST", "/v1/windows/freeze", body)
    assert status == 200 and result["snapshot"] == json.loads(
        path.read_bytes()
    ), "automatic_receipt_not_replayed"
    assert result["receipt"]["snapshot_sha256"] == digest(path.read_bytes()), (
        "automatic_receipt_hash_changed"
    )
    evidence = result["snapshot"]["enforcement"]
    assert len(evidence) == 1 and evidence[0]["closure_reason"] == reason, (
        "automatic_reason_wrong"
    )
    totals = result["snapshot"]["profiles"][0]
    delta = (
        totals["upload_bytes"]
        - window["baseline_upload_bytes"]
        + totals["download_bytes"]
        - window["baseline_download_bytes"]
    )
    assert (
        evidence[0]["admitted_bytes"] == delta <= window["allocated_bytes"]
    ), "strict_final_budget_truth"
    assert core.profile(1)["active_operations"] == 0, (
        "strict_final_operations_not_joined"
    )
    return body, result


def accept_and_rotate(
    core: Core,
    fixture: WindowFixture,
    body: dict[str, Any],
    receipt: dict[str, Any],
    grant_id: int,
    budget: int,
    validity: float = 90,
) -> dict[str, Any]:
    totals = receipt["snapshot"]["profiles"][0]
    acceptance = {
        "acceptance_id": uuid.uuid4().hex,
        "epoch": core.epoch,
        "profile_id": 1,
        "barrier_id": body["barrier_id"],
        "snapshot_sha256": receipt["receipt"]["snapshot_sha256"],
    }
    status, accepted = core.request(
        "POST", "/v1/windows/accept-predecessor", acceptance
    )
    assert status == 200, "strict_predecessor_rejected"
    window = fixture.grant(
        core,
        1,
        grant_id,
        (totals["upload_bytes"], totals["download_bytes"]),
        acceptance,
        budget,
        validity,
    )
    admitted(core, window)
    status, old = core.request("POST", "/v1/windows/freeze", body)
    assert status == 200 and old == receipt, "strict_old_receipt_changed"
    status, replay = core.request(
        "POST", "/v1/windows/accept-predecessor", acceptance
    )
    assert (
        status == 200
        and replay == accepted
        and core.profile(1)["phase"] == "open"
    ), "old_action_closed_strict_replacement"
    return window


def controlled_download(
    core: Core, target: Upstream, window: dict[str, Any]
) -> None:
    # Owned outbound bytes wait for the native decoded reader's reservation.
    # No engine hook/mock participates.
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        profile = core.profile(1)
        if (
            profile["totals"]["upload_bytes"]
            == window["baseline_upload_bytes"] + 1
            and profile["operation_kinds"].get("decoded_read", 0) == 1
        ):
            break
        time.sleep(0.01)
    assert (
        profile["totals"]["upload_bytes"]
        == window["baseline_upload_bytes"] + 1
        and profile["operation_kinds"].get("decoded_read", 0) == 1
    ), "idle_reserved_read_not_observed"
    with target.lock:
        sockets = list(target.sockets)
    assert len(sockets) == 1, "owned_controlled_outbound_socket_missing"
    sockets[0].sendall(b"D" * 256)


def exercise_strict_windows(
    core: Core,
    fixture: WindowFixture,
    clients: list[StockClient],
    b: socket.socket,
    echo: Upstream,
    sink: Upstream,
    burst: Upstream,
    contention: Upstream,
    body: dict[str, Any],
    receipt: dict[str, Any],
) -> None:
    global CURRENT_STAGE
    CURRENT_STAGE = "strict_policy_mismatch"
    wrong = fixture.grant(core, 1, 4)
    wrong["enforcement_sha256"] = "f" * 64
    status, _ = core.request("POST", "/v1/windows/admit", wrong)
    assert status == 409, "strict_changed_policy_admitted"
    CURRENT_STAGE = "strict_aggregate_exhaustion"
    window = accept_and_rotate(core, fixture, body, receipt, 4, 192)
    first, second = (
        clients[0].connect(sink.port),
        clients[0].connect(sink.port),
    )
    first.sendall(b"A" * 48)
    second.sendall(b"B" * 48)
    expected = window["baseline_upload_bytes"] + 96
    deadline = time.monotonic() + 3
    while (
        time.monotonic() < deadline
        and core.profile(1)["totals"]["upload_bytes"] != expected
    ):
        time.sleep(0.01)
    assert core.profile(1)["totals"]["upload_bytes"] == expected, (
        "both_sessions_known_upload_missing"
    )
    for connection in (first, second):
        try:
            connection.sendall(b"Q" * 512)
        except OSError:
            pass  # Exhaustion may close the second socket before sendall.
    body, receipt = automatic_receipt(core, window, "budget_exhausted")
    assert receipt["snapshot"]["enforcement"][0]["admitted_bytes"] == 192, (
        "aggregate_budget_not_exact"
    )
    assert (
        receipt["snapshot"]["profiles"][0]["download_bytes"]
        == window["baseline_download_bytes"]
    ), "sink_counted_delivery"
    denied(clients[0], echo.port, first)
    denied(clients[0], echo.port, second)
    roundtrip(b, b"B-same-socket-after-exhaustion")
    CURRENT_STAGE = "strict_deadline_residual_first_flush"
    window = accept_and_rotate(core, fixture, body, receipt, 5, 33, 0.7)
    a = clients[0].connect(burst.port)
    a.sendall(b"F")
    controlled_download(core, burst, window)
    prefix = a.recv(256)
    assert prefix and set(prefix) == {ord("D")} and len(prefix) <= 32, (
        "strict_first_flush_payload_wrong"
    )
    body, receipt = automatic_receipt(core, window, "window_expired")
    totals = receipt["snapshot"]["profiles"][0]
    assert 0 < receipt["snapshot"]["enforcement"][0]["admitted_bytes"] < 33, (
        "expiry_minted_full_budget"
    )
    assert totals.get("unadmitted_download_bytes", 0) >= 224, (
        "unadmitted_prefix_remainder_evidence_missing"
    )
    denied(clients[0], echo.port, a)
    roundtrip(b, b"B-same-socket-after-deadline")
    CURRENT_STAGE = "strict_idle_reservation_contention"
    window = accept_and_rotate(core, fixture, body, receipt, 6, 16)
    a = clients[0].connect(contention.port)
    a.sendall(b"F")
    controlled_download(core, contention, window)
    body, receipt = automatic_receipt(core, window, "reservation_contention")
    assert receipt["snapshot"]["enforcement"][0]["admitted_bytes"] < 16, (
        "contention_claimed_exhaustion"
    )
    denied(clients[0], echo.port, a)
    roundtrip(b, b"B-same-socket-after-contention")
    CURRENT_STAGE = "strict_final_re_admit_baseline"
    window = accept_and_rotate(core, fixture, body, receipt, 7, 1000000)
    CURRENT_STAGE = "strict_final_new_A_connect"
    a = clients[0].connect(echo.port)
    CURRENT_STAGE = "strict_final_new_A_payload"
    roundtrip(a, b"A-reopened-after-three-automatic-barriers")
    CURRENT_STAGE = "strict_final_same_B_payload"
    roundtrip(b, b"B-still-same-socket-after-strict-rotation")
    CURRENT_STAGE = "strict_final_manual_freeze"
    _, final = freeze_lost_response(core, window)
    assert (
        final["snapshot"]["enforcement"][0]["closure_reason"]
        == "manual_freeze"
    ), "manual_final_reason_wrong"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--stock-binary", type=Path, required=True)
    parser.add_argument("--stock-references", type=Path, required=True)
    parser.add_argument(
        "--mode", choices=("tls", "reality", "all"), default="all"
    )
    parser.add_argument(
        "--enforcement", choices=("metadata", "strict"), default="metadata"
    )
    args = parser.parse_args()
    cases: dict[str, bool] = {}
    phase = "reference"
    started = time.monotonic()

    def deadline(*_: object) -> None:
        raise TimeoutError("owned_window_probe_deadline")

    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(120)
    try:
        with tempfile.TemporaryDirectory(
            prefix="papilio-managed-window-"
        ) as directory:
            root = Path(directory)
            root.chmod(0o700)
            stock = stage_stock(args.stock_binary, args.stock_references, root)
            modes = ("tls", "reality") if args.mode == "all" else (args.mode,)
            for mode in modes:
                phase = mode
                case_root = root / mode
                case_root.mkdir(mode=0o700)
                exercise(
                    args.binary,
                    stock,
                    case_root,
                    mode,
                    args.enforcement == "strict",
                )
                cases[
                    f"actual_stock_{mode}_closed_windows_A_rotation_B_same_session_replays"
                ] = True
                if args.enforcement == "strict":
                    cases[
                        f"actual_stock_{mode}_strict_aggregate_expiry_contention_residual_rotation"
                    ] = True
                    cases[
                        f"actual_stock_{mode}_strict_closed_startup_original_receipt_replay"
                    ] = True
        print(
            json.dumps(
                {
                    "state": "passed",
                    "scope": "isolated_local_window_component",
                    "cases": cases,
                    "duration_seconds": round(time.monotonic() - started, 3),
                    "owned_cleanup": True,
                    "api_authority": False,
                    "budget_enforced": False,
                    "deadline_enforced": False,
                }
            )
        )
        return 0
    except Exception as error:
        print(
            json.dumps(
                {
                    "state": "failed",
                    "phase": phase,
                    "stage": CURRENT_STAGE,
                    "safe_error_type": type(error).__name__,
                    "safe_failure_code": str(error)
                    if isinstance(error, AssertionError)
                    and str(error) in ALLOWED_FAILURE_CODES
                    else "unclassified",
                    "cases": cases,
                    "duration_seconds": round(time.monotonic() - started, 3),
                    "startup_diagnostic": barrier_probe.STARTUP_DIAGNOSTIC,
                    "strict_diagnostic": STRICT_DIAGNOSTIC,
                    "api_authority": False,
                    "budget_enforced": False,
                    "deadline_enforced": False,
                }
            )
        )
        return 1
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    raise SystemExit(main())
