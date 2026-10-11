"""Actual paid TLS traffic through three exact native window identities."""

import json
import os
import re
import socket
import time
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from tests.managed_installation_agent import compact, digest
from tests.managed_ip_agent import (
    BoundStockClient,
    EchoTarget,
    InstalledTlsEndpoints,
    UnixHTTP,
    launch,
    private_write,
    roundtrip,
    stage_stock,
)


@dataclass(frozen=True, slots=True)
class NativeSuccessorResult:
    initial: dict
    successors: tuple[dict, ...]
    replay_unchanged: bool
    child_stopped: bool


def exact_open_entry(root, process, profile_id, index, timeout):
    deadline = time.monotonic() + timeout
    initial_path = root / "managed-agent" / "managed-window-cycle.json"
    chain_path = root / "managed-agent" / "managed-window-successors.json"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            diagnostic = (root / "successor-agent.log").read_text().strip()
            safe = (
                diagnostic
                if re.fullmatch(
                    r"managed_[a-z_]+|node API status [0-9]{3}", diagnostic
                )
                else "unclassified"
            )
            raise AssertionError(
                "native_successor_exited_before_admit:" + safe
            )
        entry = None
        if initial_path.exists():
            initial = json.loads(initial_path.read_bytes())
            if index == 0 and initial.get("paid_acceptance"):
                entry = initial
            elif index > 0 and initial.get("finality") and chain_path.exists():
                entries = json.loads(chain_path.read_bytes())["entries"]
                if len(entries) >= index and all(
                    previous.get("finality")
                    for previous in entries[: index - 1]
                ):
                    entry = entries[index - 1]
        if (
            entry
            and entry.get("issued")
            and entry.get("admission")
            and not entry.get("finality")
        ):
            wire = entry["issued"]["window"]
            original = entry["admission"]
            connection = UnixHTTP(root / "control" / "control.sock")
            try:
                connection.request(
                    "GET", "/v1/windows/admissions/" + wire["window_id"]
                )
                response = connection.getresponse()
                current_bytes = response.read(131073)
                current = json.loads(current_bytes)
                exact = (
                    response.status == 200
                    and current_bytes == original["original_receipt"].encode()
                    and current["window"]["window_id"] == wire["window_id"]
                    and current["window"]["grant_id"] == wire["grant_id"]
                    and current["window"]["binding"] == wire["binding"]
                    and response.getheader("X-Papilio-Receipt-Window-ID")
                    == wire["window_id"]
                    and response.getheader("X-Papilio-Receipt-Epoch")
                    == wire["epoch"]
                    and response.getheader("X-Papilio-Receipt-SHA256")
                    == digest(current_bytes)
                    == original["receipt"]["receipt_sha256"]
                    and int(response.getheader("X-Papilio-Receipt-Bytes", "0"))
                    == len(current_bytes)
                    == original["receipt"]["bytes"]
                    and current["window_sha256"]
                    == entry["issued"]["window_sha256"]
                )
                connection.close()
                connection = UnixHTTP(root / "control" / "control.sock")
                connection.request("GET", "/v1/observe")
                response = connection.getresponse()
                observation = json.loads(response.read(131073))
                if (
                    exact
                    and response.status == 200
                    and observation["epoch"] == wire["epoch"]
                ):
                    profile = next(
                        row
                        for row in observation["profiles"]
                        if row["totals"]["binding"]["profile_id"] == profile_id
                    )
                    if (
                        profile["phase"] == "open"
                        and profile["totals"]["binding"] == wire["binding"]
                        and profile["totals"]["upload_bytes"]
                        == wire["baseline_upload_bytes"]
                        and profile["totals"]["download_bytes"]
                        == wire["baseline_download_bytes"]
                        and profile["budget"]["allocated_bytes"]
                        == wire["allocated_bytes"]
                        and profile["budget"]["admitted_bytes"] == 0
                        and profile["budget"]["reserved_bytes"] == 0
                    ):
                        return entry
            except (OSError, ValueError, KeyError):
                pass
            finally:
                connection.close()
        time.sleep(0.02)
    raise AssertionError("native_successor_exact_open_timeout")


def run_native_successor_cycles(
    root: Path,
    runtime_binary: Path,
    registry: dict,
    installation_id: int,
    profile_id: int,
    api_url: str,
    node: dict,
    binaries: Path,
    task_id: int,
    payloads: tuple[bytes, bytes, bytes],
    *,
    freeze_after_ms: int,
) -> NativeSuccessorResult:
    cycles = tuple(
        {
            "request_key": f"native-successor-{installation_id}-{index}",
            "requested_bytes": 1024,
            "freeze_after_ms": freeze_after_ms,
            "operation_timeout_ms": 5000,
            "retry_interval_ms": 100,
            "max_attempts": 3,
        }
        for index in (1, 2)
    )
    managed = {
        **registry,
        "installation_id": installation_id,
        "window_cycle": {
            "enabled": True,
            "profile_id": profile_id,
            "generation": 0,
            "request_key": f"native-successor-initial-{installation_id}",
            "requested_bytes": 1024,
            "freeze_after_ms": freeze_after_ms,
            "operation_timeout_ms": 5000,
            "retry_interval_ms": 100,
            "max_attempts": 3,
            "require_admission_receipt": True,
            "provision_task_id": task_id,
        },
        "successor_cycles": {
            "enabled": True,
            "max_successor_cycles": 2,
            "api_max_successors": 3,
            "cycles": cycles,
        },
    }
    config = {
        "enabled": True,
        "api_url": api_url,
        "node_code": node["node"]["code"],
        "state_directory": str(root / "unused-stock-state"),
        "managed_installation": managed,
        "poll_interval_ms": 300,
        "http_timeout_ms": 15000,
        "max_response_bytes": 2097152,
        "max_idle_connections": 2,
        "page_size": 8,
        "max_pages_per_poll": 2,
    }
    config_path = root / "successor-agent-config.json"
    private_write(config_path, compact(config))
    environment = {**os.environ, "PAPILIO_NODE_KEY": node["agent_key"]}
    command = [str(runtime_binary), "-config", str(config_path), "-once"]
    with ExitStack() as stack:
        stock = stage_stock(
            root, binaries / "xray", binaries.parent / "artifacts.json"
        )
        process = launch(
            command,
            stack,
            root / "successor-agent.log",
            environment=environment,
        )
        initial = exact_open_entry(root, process, profile_id, 0, 20)
        installation = json.loads(
            (root / "managed-agent" / "managed-installation.json").read_bytes()
        )
        artifact = installation["claim"]["artifact_content"]
        assert (
            digest(artifact.encode())
            == installation["claim"]["expectation"]["artifact_sha256"]
        )
        binding = initial["issued"]["window"]["binding"]
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
        seen = set()
        baseline = 0
        for index, payload in enumerate(payloads):
            entry = (
                initial
                if index == 0
                else exact_open_entry(root, process, profile_id, index, 20)
            )
            wire = entry["issued"]["window"]
            assert wire["window_id"] not in seen, (
                "native_successor_reused_open_identity"
            )
            seen.add(wire["window_id"])
            assert wire["baseline_upload_bytes"] == baseline
            assert wire["baseline_download_bytes"] == baseline
            assert entry["admission"]["admission"]["budget_enforced"]
            assert entry["admission"]["admission"]["deadline_enforced"]
            connection = client.connect(target.port)
            roundtrip(connection, payload)
            connection.close()
            baseline += len(payload)
        assert process.wait(timeout=30) == 0, "native_successor_chain_failed"
        initial_path = root / "managed-agent" / "managed-window-cycle.json"
        chain_path = root / "managed-agent" / "managed-window-successors.json"
        initial_bytes, chain_bytes = (
            initial_path.read_bytes(),
            chain_path.read_bytes(),
        )
        completed = json.loads(initial_bytes)
        successors = tuple(json.loads(chain_bytes)["entries"])
        assert len(successors) == 2 and completed.get("finality")
        for entry, payload in zip(
            (completed, *successors), payloads, strict=True
        ):
            assert entry.get("finality"), (
                "native_successor_finality_not_durable"
            )
            assert entry["finality"]["upload_bytes"] == len(payload)
            assert entry["finality"]["download_bytes"] == len(payload)
            submission = entry["submission"]
            assert (
                digest(submission["original_receipt"].encode())
                == submission["receipt"]["snapshot_sha256"]
            )
        settings = root / "managed-agent" / "managed-settings.json"
        identity = settings.stat().st_ino, settings.stat().st_mtime_ns
        assert not (root / "control" / "control.sock").exists()
        replay = launch(
            command,
            stack,
            root / "successor-agent-replay.log",
            environment=environment,
        )
        assert replay.wait(timeout=15) == 0, (
            "native_successor_completed_replay_failed"
        )
        unchanged = (
            initial_path.read_bytes() == initial_bytes
            and chain_path.read_bytes() == chain_bytes
            and (settings.stat().st_ino, settings.stat().st_mtime_ns)
            == identity
            and not (root / "control" / "control.sock").exists()
        )
        with socket.socket() as check:
            check.settimeout(0.1)
            stopped = check.connect_ex(("127.0.0.1", inbound["port"])) != 0
        assert unchanged and stopped, (
            "native_successor_replay_relaunched_child"
        )
        return NativeSuccessorResult(completed, successors, unchanged, stopped)
