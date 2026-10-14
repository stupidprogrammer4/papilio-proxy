"""Actual paid TLS traffic through native windows and epoch rollover."""

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
    entries: tuple[dict, ...]
    replay_unchanged: bool
    child_stopped: bool


def epoch_journal(root, epoch_index):
    if epoch_index == 0:
        return root / "managed-agent"
    active_path = root / "control" / "epoch-active.json"
    if not active_path.exists():
        return None
    try:
        active = json.loads(active_path.read_bytes())
        if len(active.get("history", [])) < epoch_index:
            return None
        return root / "managed-agent" / "epochs" / active["epoch"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def exact_open_entry(root, process, profile_id, index, timeout, epoch_index=0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            diagnostic = (root / "successor-agent.log").read_text().strip()
            try:
                structured = json.loads(diagnostic)
                diagnostic = structured.get("error", diagnostic)
            except (ValueError, AttributeError):
                pass
            tokens = re.findall(
                r"managed_[a-z0-9_]+|node API status [0-9]{3}", diagnostic
            )
            if tokens:
                diagnostic = tokens[0]
            safe = (
                diagnostic
                if re.fullmatch(
                    r"managed_[a-z0-9_]+|node API status [0-9]{3}", diagnostic
                )
                else "unclassified"
            )
            active_summary = "missing"
            try:
                active = json.loads(
                    (root / "control" / "epoch-active.json").read_bytes()
                )
                active_summary = (
                    active.get("epoch", "")[:8]
                    + ":"
                    + active.get("state", "")
                    + ":history="
                    + str(len(active.get("history", [])))
                )
            except (OSError, ValueError, AttributeError):
                pass
            pending_summary = "missing"
            try:
                installation_state = json.loads(
                    (
                        root / "managed-agent" / "managed-installation.json"
                    ).read_bytes()
                )
                submission = installation_state.get(
                    "pending_rollover", {}
                ).get("submission")
                if submission:
                    pending_summary = submission["receipt"]["epoch"][:8]
            except (OSError, ValueError, KeyError, AttributeError, TypeError):
                pass
            raise AssertionError(
                "native_successor_exited_before_admit:"
                + safe
                + ":active="
                + active_summary
                + ":pending="
                + pending_summary
            )
        directory = epoch_journal(root, epoch_index)
        initial_path = (
            directory / "managed-window-cycle.json" if directory else None
        )
        chain_path = (
            directory / "managed-window-successors.json" if directory else None
        )
        entry = None
        if initial_path and initial_path.exists():
            initial = json.loads(initial_path.read_bytes())
            if index == 0 and initial.get("paid_acceptance"):
                entry = initial
            elif (
                index == 0
                and initial.get("request", {}).get("provision_task_id", 0) == 0
            ):
                entry = initial
            elif (
                index > 0
                and initial.get("finality")
                and chain_path
                and chain_path.exists()
            ):
                entries = json.loads(chain_path.read_bytes())["entries"]
                if len(entries) >= index and all(
                    previous.get("finality")
                    for previous in entries[: index - 1]
                ):
                    entry = entries[index - 1]
        if entry and entry.get("issued") and not entry.get("finality"):
            wire = entry["issued"]["window"]
            original = entry.get("admission")
            connection = UnixHTTP(root / "control" / "control.sock")
            try:
                exact = original is None
                if original is not None:
                    connection.request(
                        "GET", "/v1/windows/admissions/" + wire["window_id"]
                    )
                    response = connection.getresponse()
                    current_bytes = response.read(131073)
                    current = json.loads(current_bytes)
                    exact = (
                        response.status == 200
                        and current_bytes
                        == original["original_receipt"].encode()
                        and current["window"]["window_id"] == wire["window_id"]
                        and current["window"]["grant_id"] == wire["grant_id"]
                        and current["window"]["binding"] == wire["binding"]
                        and response.getheader("X-Papilio-Receipt-Window-ID")
                        == wire["window_id"]
                        and response.getheader("X-Papilio-Receipt-Epoch")
                        == wire["epoch"]
                        and response.getheader("X-Papilio-Receipt-SHA256")
                        == digest(current_bytes)
                        and response.getheader("X-Papilio-Receipt-SHA256")
                        == original["receipt"]["receipt_sha256"]
                        and int(
                            response.getheader("X-Papilio-Receipt-Bytes", "0")
                        )
                        == len(current_bytes)
                        and len(current_bytes) == original["receipt"]["bytes"]
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
    payloads: tuple[bytes, ...],
    *,
    freeze_after_ms: int,
    max_epochs: int = 1,
) -> NativeSuccessorResult:
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
            "template": {
                "request_key": f"native-successor-{installation_id}",
                "requested_bytes": 1024,
                "freeze_after_ms": freeze_after_ms,
                "operation_timeout_ms": 5000,
                "retry_interval_ms": 100,
                "max_attempts": 3,
            },
        },
        "epoch_seal": {
            "enabled": True,
            "request_id": f"{installation_id:032x}",
            "operation_timeout_ms": 5000,
            "retry_interval_ms": 100,
            "max_attempts": 3,
            "max_receipt_bytes": 131072,
            "max_profiles": 16,
            "max_windows": 8,
            "max_journal_bytes": 4194304,
            "max_epochs": max_epochs,
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
    command = [str(runtime_binary), "-config", str(config_path)]
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
        entries = []
        for index, payload in enumerate(payloads):
            epoch_index, cycle_index = divmod(index, 3)
            if cycle_index == 0:
                baseline = 0
            entry = (
                initial
                if index == 0
                else exact_open_entry(
                    root, process, profile_id, cycle_index, 45, epoch_index
                )
            )
            wire = entry["issued"]["window"]
            assert wire["window_id"] not in seen, (
                "native_successor_reused_open_identity"
            )
            seen.add(wire["window_id"])
            entries.append(entry)
            assert wire["baseline_upload_bytes"] == baseline
            assert wire["baseline_download_bytes"] == baseline
            if index == 0:
                assert entry["admission"]["admission"]["budget_enforced"]
                assert entry["admission"]["admission"]["deadline_enforced"]
            if epoch_index > 0:
                assert entry.get("admission") is None
            connection = client.connect(target.port)
            roundtrip(connection, payload)
            connection.close()
            baseline += len(payload)
        exit_code = process.wait(timeout=30)
        if exit_code:
            diagnostic = (root / "successor-agent.log").read_text().strip()
            seal_path = root / "managed-agent" / "managed-epoch-seal.json"
            seal_stage = "missing"
            if seal_path.exists():
                try:
                    seal = json.loads(seal_path.read_bytes())
                    seal_stage = (
                        "applied"
                        if seal.get("acceptance_applied")
                        else "api_accepted"
                        if seal.get("acceptance")
                        else "original_saved"
                    )
                except (OSError, ValueError):
                    seal_stage = "invalid"
            safe = (
                diagnostic
                if re.fullmatch(
                    r"managed_[a-z0-9_]+|node API status [0-9]{3}", diagnostic
                )
                else "unclassified"
            )
            active_summary = "missing"
            try:
                active = json.loads(
                    (root / "control" / "epoch-active.json").read_bytes()
                )
                active_summary = (
                    active.get("epoch", "")[:8]
                    + ":"
                    + active.get("state", "")
                    + ":history="
                    + str(len(active.get("history", [])))
                )
            except (OSError, ValueError, AttributeError):
                pass
            pending_summary = "missing"
            try:
                installation_state = json.loads(
                    (
                        root / "managed-agent" / "managed-installation.json"
                    ).read_bytes()
                )
                submission = installation_state.get(
                    "pending_rollover", {}
                ).get("submission")
                if submission:
                    pending_summary = submission["receipt"]["epoch"][:8]
            except (OSError, ValueError, KeyError, AttributeError, TypeError):
                pass
            raise AssertionError(
                "native_successor_chain_failed:"
                + safe
                + ":active="
                + active_summary
                + ":seal="
                + seal_stage
                + ":pending="
                + pending_summary
            )
        epoch_record = json.loads(
            (root / "control" / "epoch-active.json").read_bytes()
        )
        assert epoch_record["state"] == "sealed_accepted"
        assert len(epoch_record.get("history", [])) == max_epochs - 1
        journal_directories = [root / "managed-agent"]
        if max_epochs > 1:
            journal_directories.append(
                root / "managed-agent" / "epochs" / epoch_record["epoch"]
            )
        journal_snapshots = []
        finalized_entries = []
        for directory in journal_directories:
            initial_path = directory / "managed-window-cycle.json"
            chain_path = directory / "managed-window-successors.json"
            seal_path = directory / "managed-epoch-seal.json"
            initial_bytes, chain_bytes, seal_bytes = (
                initial_path.read_bytes(),
                chain_path.read_bytes(),
                seal_path.read_bytes(),
            )
            seal_state = json.loads(seal_bytes)
            completed = json.loads(initial_bytes)
            assert seal_state["acceptance_applied"]
            assert (
                seal_state["acceptance"]["epoch"]
                == completed["request"]["process_epoch"]
            )
            chain = json.loads(chain_bytes)
            assert len(chain["entries"]) == 2
            assert (
                chain["stop_reason"] == "managed_successor_cycle_cap_reached"
            )
            finalized_entries.extend((completed, *chain["entries"]))
            journal_snapshots.append(
                (
                    initial_path,
                    initial_bytes,
                    chain_path,
                    chain_bytes,
                    seal_path,
                    seal_bytes,
                )
            )
        entries = finalized_entries
        assert len(entries) == len(payloads)
        component_epoch = epoch_record
        assert component_epoch["acceptance"]
        for entry, payload in zip(entries, payloads, strict=True):
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
            all(
                initial_path.read_bytes() == initial_bytes
                and chain_path.read_bytes() == chain_bytes
                and seal_path.read_bytes() == seal_bytes
                for (
                    initial_path,
                    initial_bytes,
                    chain_path,
                    chain_bytes,
                    seal_path,
                    seal_bytes,
                ) in journal_snapshots
            )
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
        return NativeSuccessorResult(
            entries[0], tuple(entries[1:]), tuple(entries), unchanged, stopped
        )
