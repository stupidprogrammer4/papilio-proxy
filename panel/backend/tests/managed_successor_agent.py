"""Actual paid TLS traffic through native windows and epoch rollover."""

import json
import os
import re
import signal
import socket
import subprocess
import time
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tests.managed_epoch_fault_relay import ManagedRolloverResponseDrop
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
    wait_closed,
)


@dataclass(frozen=True, slots=True)
class NativeSuccessorResult:
    initial: dict
    successors: tuple[dict, ...]
    entries: tuple[dict, ...]
    replay_unchanged: bool
    child_stopped: bool


@dataclass(frozen=True, slots=True)
class ManagedBatchProfileInput:
    profile_id: int
    generation: int
    provision_task_id: int
    requested_bytes: int


@dataclass(frozen=True, slots=True)
class NativeWindowBatchResult:
    entries: tuple[dict, ...]
    independent_traffic: bool
    quota_closed: bool
    expiry_closed: bool
    post_expiry_outage_seconds: float


@dataclass(frozen=True, slots=True)
class NativeManagedCrashResult:
    managed_child_exited: bool
    established_connection_closed: bool
    restart_refused: bool
    no_finality: bool
    freeze_intent_durable: bool


def wait_for_managed_batch_epoch(
    root: Path,
    process,
    profiles: tuple[ManagedBatchProfileInput, ...],
    epoch_index: int,
    timeout: float,
    managed_binary: Path,
) -> tuple[Path, dict[int, dict]]:
    deadline = time.monotonic() + timeout
    result_directory = None
    result_states: dict[int, dict] = {}
    state_summary: dict[int, dict] = {}
    while time.monotonic() < deadline:
        if process.poll() is not None:
            diagnostic = (root / "window-batch-agent.log").read_text().strip()
            try:
                structured = json.loads(diagnostic)
                diagnostic = structured.get("error", diagnostic)
            except (ValueError, AttributeError):
                pass
            tokens = re.findall(
                r"managed_[a-z0-9_]+|node API status [0-9]{3}|"
                r"runtime API (?:unavailable|response invalid|"
                r"response capacity or encoding rejected)",
                diagnostic,
            )
            safe = tokens[-1] if tokens else "unclassified"
            settings_path = root / "managed-agent" / "managed-settings.json"
            if safe == "managed_child_exited" and settings_path.is_file():
                config = json.loads(
                    (root / "window-batch-agent-config.json").read_bytes()
                )["managed_installation"]
                checked = subprocess.run(
                    [
                        str(managed_binary),
                        "--check",
                        "--config",
                        str(settings_path),
                        "--max-config-bytes",
                        str(config["max_settings_bytes"]),
                        "--max-config-depth",
                        str(config["max_settings_depth"]),
                    ],
                    capture_output=True,
                    timeout=20,
                    env={
                        key: value
                        for key, value in os.environ.items()
                        if key != "PAPILIO_NODE_KEY"
                    },
                )
                try:
                    checked_result = json.loads(checked.stdout)
                    checked_error = checked_result.get("error", "")
                except (ValueError, AttributeError):
                    checked_error = ""
                checked_tokens = re.findall(
                    r"managed_[a-z0-9_]+", checked_error
                )
                if checked.returncode and checked_tokens:
                    safe = checked_tokens[0]
            raise AssertionError(
                "native_window_batch_exited_before_admit:" + safe
            )
        directory = epoch_journal(root, epoch_index)
        try:
            if directory is None:
                time.sleep(0.02)
                continue
            states = {}
            state_summary = {}
            for item in profiles:
                state_path = (
                    directory
                    / "managed-window-profiles"
                    / str(item.profile_id)
                    / "managed-window-cycle.json"
                )
                state = json.loads(state_path.read_bytes())
                state_summary[item.profile_id] = {
                    "issued": state.get("issued") is not None,
                    "admission": state.get("admission") is not None,
                    "paid_acceptance": state.get("paid_acceptance")
                    is not None,
                    "local_admitted": state.get("local_admitted") is True,
                    "submission": state.get("submission") is not None,
                    "finality": state.get("finality") is not None,
                }
                admitted = (
                    state.get("admission") is not None
                    and state.get("paid_acceptance") is not None
                    if item.provision_task_id > 0
                    else state.get("local_admitted") is True
                )
                if state.get("issued") is None or not admitted:
                    raise ValueError("managed window not yet admitted")
                states[item.profile_id] = state
            observation = UnixHTTP(root / "control" / "control.sock")
            try:
                observation.request("GET", "/v1/observe")
                response = observation.getresponse()
                document = json.loads(response.read(131073))
            finally:
                observation.close()
            profiles_by_id = {
                row["totals"]["binding"]["profile_id"]: row
                for row in document["profiles"]
            }
            if all(
                profiles_by_id[item.profile_id]["phase"] == "open"
                and profiles_by_id[item.profile_id]["totals"]["binding"]
                == states[item.profile_id]["issued"]["window"]["binding"]
                and profiles_by_id[item.profile_id]["budget"]["admitted_bytes"]
                == 0
                for item in profiles
            ):
                result_directory = directory
                result_states = states
                break
        except (OSError, ValueError, KeyError, TypeError):
            pass
        time.sleep(0.02)
    if result_directory is None:
        try:
            observation = observe_managed_batch_profiles(root)
        except (OSError, ValueError, KeyError, TypeError):
            observation = {}
        process_state = process.poll()
        agent_error = "running" if process_state is None else "unclassified"
        if process_state is not None:
            try:
                diagnostic = json.loads(
                    (root / "window-batch-agent.log").read_text()
                ).get("error", "")
            except (OSError, ValueError, AttributeError):
                diagnostic = ""
            tokens = re.findall(r"managed_[a-z0-9_]+", diagnostic)
            agent_error = tokens[-1] if tokens else "unclassified"
        raise AssertionError(
            f"native_window_batch_open_timeout:{state_summary}:"
            f"{observation}:{agent_error}"
        )
    return result_directory, result_states


def observe_managed_batch_profiles(root: Path) -> dict[int, dict]:
    connection = UnixHTTP(root / "control" / "control.sock")
    try:
        connection.request("GET", "/v1/observe")
        response = connection.getresponse()
        document = json.loads(response.read(131073))
    finally:
        connection.close()
    summary = {}
    for item in document["profiles"]:
        binding = item["totals"]["binding"]
        budget = item.get("budget") or {}
        summary[binding["profile_id"]] = {
            "phase": item["phase"],
            "upload": item["totals"]["upload_bytes"],
            "download": item["totals"]["download_bytes"],
            "admitted": budget.get("admitted_bytes"),
            "reserved": budget.get("reserved_bytes"),
            "closure": budget.get("closure_reason"),
        }
    return summary


def wait_managed_window_expiry(
    connection: socket.socket, seconds: float
) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            roundtrip(connection, b"x")
        except (OSError, EOFError):
            return
        time.sleep(min(0.5, deadline - time.monotonic()))
    raise AssertionError("native_window_expiry_did_not_close")


def wait_for_managed_batch_finality(
    root: Path,
    process,
    directory: Path,
    profiles: tuple[ManagedBatchProfileInput, ...],
    timeout: float,
) -> dict[int, dict]:
    deadline = time.monotonic() + timeout
    result = {}
    while time.monotonic() < deadline:
        result = {}
        for item in profiles:
            state_path = (
                directory
                / "managed-window-profiles"
                / str(item.profile_id)
                / "managed-window-cycle.json"
            )
            try:
                result[item.profile_id] = json.loads(state_path.read_bytes())
            except (OSError, ValueError):
                pass
        complete = all(
            result.get(item.profile_id, {}).get("submission") is not None
            and result[item.profile_id].get("finality") is not None
            for item in profiles
        )
        if complete:
            return result
        if process.poll() is not None:
            break
        time.sleep(0.02)
    missing = {
        item.profile_id: {
            "issued": result.get(item.profile_id, {}).get("issued")
            is not None,
            "submission": result.get(item.profile_id, {}).get("submission")
            is not None,
            "finality": result.get(item.profile_id, {}).get("finality")
            is not None,
        }
        for item in profiles
    }
    agent_error = "still_running"
    if process.poll() is None:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    if process.poll() is not None:
        try:
            diagnostic = (root / "window-batch-agent.log").read_text().strip()
        except OSError:
            diagnostic = ""
        try:
            structured = json.loads(diagnostic)
            diagnostic = structured.get("error", diagnostic)
        except (ValueError, AttributeError):
            pass
        tokens = re.findall(
            r"managed_[a-z0-9_]+|node API status [0-9]{3}|"
            r"runtime API (?:unavailable|response invalid|"
            r"response capacity or encoding rejected)",
            diagnostic,
        )
        agent_error = tokens[-1] if tokens else "unclassified"
    try:
        observations = observe_managed_batch_profiles(root)
    except (OSError, ValueError, KeyError, TypeError):
        observations = {}
    raise AssertionError(
        f"native_window_batch_finality_unresolved:{missing}:"
        f"{agent_error}:{observations}"
    )


def run_native_managed_window_batch(
    root: Path,
    runtime_binary: Path,
    registry: dict,
    installation_id: int,
    profiles: tuple[ManagedBatchProfileInput, ...],
    api_url: str,
    node: dict,
    binaries: Path,
    *,
    freeze_after_ms: int,
    validity_ms: int,
    post_expiry_outage_seconds: float,
    api_fault: ManagedRolloverResponseDrop,
) -> NativeWindowBatchResult:
    if len(profiles) != 2 or len(
        {item.profile_id for item in profiles}
    ) != len(profiles):
        raise AssertionError("native_window_batch_profile_set_invalid")
    ordered_profiles = tuple(
        sorted(profiles, key=lambda item: item.profile_id)
    )
    profiles_by_budget = {
        item.requested_bytes: item for item in ordered_profiles
    }
    if set(profiles_by_budget) != {64, 65536}:
        raise AssertionError("native_window_batch_budget_profiles_invalid")
    if post_expiry_outage_seconds <= 0:
        raise AssertionError("native_window_batch_outage_duration_invalid")
    quota_profile_id = profiles_by_budget[64].profile_id
    expiry_profile_id = profiles_by_budget[65536].profile_id
    registry_policy = registry["registry"]
    registry_policy["window_policy"].update(
        {
            "max_windows": len(ordered_profiles) * 2,
            "max_records": len(ordered_profiles) * 6,
            "max_admission_receipts": len(ordered_profiles) * 2,
            "max_validity_ms": validity_ms,
            "max_epoch_seals": 2,
        }
    )
    registry_policy["component_policy"]["max_barriers"] = (
        len(ordered_profiles) * 4
    )
    registry["trusted_api_policy"]["window_policy_sha256"] = digest(
        compact(registry_policy["window_policy"], canonical=True)
    )
    batch_key = f"native-batch-{installation_id}"
    profile_policies = [
        {
            "enabled": True,
            "profile_id": item.profile_id,
            "generation": item.generation,
            "request_key": f"native-batch-profile-{item.profile_id}",
            "requested_bytes": item.requested_bytes,
            "freeze_after_ms": freeze_after_ms,
            "operation_timeout_ms": 15000,
            "retry_interval_ms": 100,
            "max_attempts": 100,
            "require_admission_receipt": item.provision_task_id > 0,
            "provision_task_id": item.provision_task_id,
        }
        for item in ordered_profiles
    ]
    managed = {
        **registry_policy,
        "installation_id": installation_id,
        "window_batch": {
            "enabled": True,
            "batch_request_key": batch_key,
            "max_profiles": len(ordered_profiles),
            "profiles": profile_policies,
        },
        "epoch_seal": {
            "enabled": True,
            "request_id": f"{installation_id:032x}",
            "operation_timeout_ms": 5000,
            "retry_interval_ms": 100,
            "max_attempts": 3,
            "max_receipt_bytes": 131072,
            "max_profiles": len(ordered_profiles),
            "max_windows": len(ordered_profiles) * 2,
            "max_journal_bytes": 4194304,
            "max_epochs": 2,
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
    config_path = root / "window-batch-agent-config.json"
    private_write(config_path, compact(config))
    environment = {**os.environ, "PAPILIO_NODE_KEY": node["agent_key"]}
    assert os.getloadavg()[0] <= 8, "native_window_batch_load_guard"
    command = [str(runtime_binary), "-config", str(config_path)]
    with ExitStack() as stack:
        stock = stage_stock(
            root, binaries / "xray", binaries.parent / "artifacts.json"
        )
        process = launch(
            command,
            stack,
            root / "window-batch-agent.log",
            environment=environment,
        )
        installation_path = (
            root / "managed-agent" / "managed-installation.json"
        )
        first_directory, first_entries = wait_for_managed_batch_epoch(
            root,
            process,
            ordered_profiles,
            0,
            30,
            Path(registry_policy["binary"]),
        )
        first_batch_path = first_directory / (
            "managed-window-batch-"
            + first_entries[quota_profile_id]["request"]["process_epoch"]
            + ".json"
        )
        first_batch = json.loads(first_batch_path.read_bytes())
        if len(first_batch.get("windows", [])) != len(ordered_profiles):
            raise AssertionError("native_window_batch_issued_set_invalid")
        installation = json.loads(installation_path.read_bytes())
        artifact = installation["claim"]["artifact_content"]
        if (
            digest(artifact.encode())
            != installation["claim"]["expectation"]["artifact_sha256"]
        ):
            raise AssertionError("native_window_batch_artifact_digest_invalid")
        document = json.loads(artifact)
        endpoints = {}
        for item in ordered_profiles:
            state = first_entries[item.profile_id]
            binding = state["issued"]["window"]["binding"]
            inbound = next(
                row
                for row in document["inbounds"]
                if row["tag"] == binding["inbound_tag"]
            )
            credential = next(
                row
                for row in inbound["settings"]["clients"]
                if row["email"] == binding["counter_identity"]
            )
            endpoints[item.profile_id] = (inbound["port"], credential["id"])
        target = EchoTarget()
        stack.callback(target.close)
        tls = InstalledTlsEndpoints(
            endpoints,
            Path(registry_policy["certificates"][0]["path"]),
        )
        first_client = BoundStockClient(
            root, stock, tls, quota_profile_id, "127.0.0.2", stack
        )
        second_client = BoundStockClient(
            root, stock, tls, expiry_profile_id, "127.0.0.3", stack
        )
        final_entries = []
        independent_traffic = False
        quota_closed = False
        expiry_closed = False
        outage_hold_elapsed = 0.0
        for epoch_index in range(2):
            directory = first_directory
            if epoch_index == 0:
                active_entries = first_entries
            else:
                rollover_profiles = tuple(
                    ManagedBatchProfileInput(
                        profile_id=item.profile_id,
                        generation=item.generation,
                        provision_task_id=0,
                        requested_bytes=item.requested_bytes,
                    )
                    for item in ordered_profiles
                )
                directory, active_entries = wait_for_managed_batch_epoch(
                    root,
                    process,
                    rollover_profiles,
                    epoch_index,
                    45,
                    Path(registry_policy["binary"]),
                )
                batch_path = directory / (
                    "managed-window-batch-"
                    + active_entries[quota_profile_id]["request"][
                        "process_epoch"
                    ]
                    + ".json"
                )
                batch = json.loads(batch_path.read_bytes())
                if len(batch.get("windows", [])) != len(ordered_profiles):
                    raise AssertionError(
                        "native_window_batch_issued_set_invalid"
                    )
            first_connection = first_client.connect(target.port)
            second_connection = second_client.connect(target.port)
            stack.callback(first_connection.close)
            stack.callback(second_connection.close)
            outage_event_offset = len(api_fault.events())
            if epoch_index == 0:
                api_fault.set_api_outage(True)
            try:
                roundtrip(first_connection, b"q" * 32)
            except (OSError, EOFError) as error:
                observation = observe_managed_batch_profiles(root)
                raise AssertionError(
                    f"native_window_batch_first_payload_closed:{observation}"
                ) from error
            wait_closed(first_connection, seconds=3)
            quota_closed = True
            roundtrip(second_connection, b"independent-user-still-active")
            independent_traffic = True
            wait_managed_window_expiry(
                second_connection,
                seconds=validity_ms // 1000 + 3,
            )
            expiry_closed = True
            if epoch_index == 0:
                if not api_fault.wait_for_outage_finality(20):
                    raise AssertionError(
                        "native_window_batch_outage_finality_not_attempted"
                    )
                outage_events = api_fault.events()[outage_event_offset:]
                if not any(
                    method == "POST"
                    and endpoint in {"finalize", "finalize_batch"}
                    and status == 503
                    for method, endpoint, status in outage_events
                ):
                    raise AssertionError(
                        "native_window_batch_outage_finality_not_rejected"
                    )
                if any(
                    status == 200
                    and endpoint
                    in {"windows", "admission", "successor", "rollover"}
                    for _, endpoint, status in outage_events
                ):
                    raise AssertionError(
                        "native_window_batch_outage_issued_authority"
                    )
                outage_hold_started = time.monotonic()
                time.sleep(post_expiry_outage_seconds)
                outage_hold_elapsed = time.monotonic() - outage_hold_started
                for item in ordered_profiles:
                    state_path = (
                        directory
                        / "managed-window-profiles"
                        / str(item.profile_id)
                        / "managed-window-cycle.json"
                    )
                    state = json.loads(state_path.read_bytes())
                    if (
                        state.get("submission") is None
                        or state.get("finality") is not None
                    ):
                        raise AssertionError(
                            "native_window_batch_outage_finality_changed"
                        )
                if outage_hold_elapsed < post_expiry_outage_seconds:
                    raise AssertionError(
                        "native_window_batch_outage_hold_incomplete"
                    )
                outage_events_after_expiry = api_fault.events()[
                    outage_event_offset:
                ]
                if any(
                    status == 200
                    for _, _, status in outage_events_after_expiry
                ):
                    raise AssertionError(
                        "native_window_batch_outage_reached_api"
                    )
                api_fault.set_api_outage(False)
            cycle_states = wait_for_managed_batch_finality(
                root, process, directory, ordered_profiles, timeout=30
            )
            for item in ordered_profiles:
                state = cycle_states[item.profile_id]
                original = json.loads(state["submission"]["original_receipt"])
                enforcement = original["enforcement"]
                if len(enforcement) != 1:
                    raise AssertionError(
                        "native_window_batch_evidence_missing"
                    )
                (window_evidence,) = enforcement
                expected_reason = (
                    "budget_exhausted"
                    if item.profile_id == quota_profile_id
                    else "window_expired"
                )
                if window_evidence["closure_reason"] != expected_reason:
                    raise AssertionError(
                        "native_window_batch_closure_reason_invalid:"
                        f"{item.profile_id}:"
                        f"{window_evidence['closure_reason']}"
                    )
                final_entries.append({**state, "snapshot": original})
        exit_code = process.wait(timeout=50)
        if exit_code:
            raise AssertionError("native_window_batch_finality_failed")
        barriers = {entry["snapshot"]["barrier_id"] for entry in final_entries}
        window_ids = {
            entry["issued"]["window"]["window_id"] for entry in final_entries
        }
        if len(barriers) != len(final_entries) or len(window_ids) != len(
            final_entries
        ):
            raise AssertionError("native_window_batch_shared_barrier")
        return NativeWindowBatchResult(
            entries=tuple(final_entries),
            independent_traffic=independent_traffic,
            quota_closed=quota_closed,
            expiry_closed=expiry_closed,
            post_expiry_outage_seconds=outage_hold_elapsed,
        )


def run_native_managed_window_crash(
    root: Path,
    runtime_binary: Path,
    registry: dict,
    installation_id: int,
    profiles: tuple[ManagedBatchProfileInput, ...],
    api_url: str,
    node: dict,
    binaries: Path,
    *,
    failure_point: Literal["core_loss", "supervisor_crash"],
) -> NativeManagedCrashResult:
    if len(profiles) != 2 or len(
        {item.profile_id for item in profiles}
    ) != len(profiles):
        raise AssertionError("native_core_loss_profile_set_invalid")
    ordered_profiles = tuple(
        sorted(profiles, key=lambda item: item.profile_id)
    )
    if failure_point not in {"core_loss", "supervisor_crash"}:
        raise AssertionError("native_managed_crash_point_invalid")
    registry_policy = registry["registry"]
    freeze_after_ms = 45000
    if failure_point == "supervisor_crash":
        freeze_after_ms = 60000
    window_policy = registry_policy["window_policy"]
    window_policy.update(
        {
            "max_windows": len(ordered_profiles) * 2,
            "max_records": len(ordered_profiles) * 6,
            "max_admission_receipts": len(ordered_profiles) * 2,
            "max_epoch_seals": 2,
        }
    )
    registry_policy["component_policy"]["max_barriers"] = (
        len(ordered_profiles) * 4
    )
    registry["trusted_api_policy"]["window_policy_sha256"] = digest(
        compact(window_policy, canonical=True)
    )
    profile_policies = [
        {
            "enabled": True,
            "profile_id": item.profile_id,
            "generation": item.generation,
            "request_key": f"native-core-loss-{item.profile_id}",
            "requested_bytes": item.requested_bytes,
            "freeze_after_ms": freeze_after_ms,
            "operation_timeout_ms": 5000,
            "retry_interval_ms": 100,
            "max_attempts": 3,
            "require_admission_receipt": item.provision_task_id > 0,
            "provision_task_id": item.provision_task_id,
        }
        for item in ordered_profiles
    ]
    managed = {
        **registry_policy,
        "installation_id": installation_id,
        "window_batch": {
            "enabled": True,
            "batch_request_key": f"native-core-loss-{installation_id}",
            "max_profiles": len(ordered_profiles),
            "profiles": profile_policies,
        },
        "epoch_seal": {
            "enabled": True,
            "request_id": f"{installation_id:032x}",
            "operation_timeout_ms": 5000,
            "retry_interval_ms": 100,
            "max_attempts": 3,
            "max_receipt_bytes": 131072,
            "max_profiles": len(ordered_profiles),
            "max_windows": len(ordered_profiles) * 2,
            "max_journal_bytes": 4194304,
            "max_epochs": 2,
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
    config_path = root / "core-loss-agent-config.json"
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
            root / "window-batch-agent.log",
            environment=environment,
        )
        directory, states = wait_for_managed_batch_epoch(
            root,
            process,
            ordered_profiles,
            0,
            30,
            Path(registry_policy["binary"]),
        )
        installation_path = (
            root / "managed-agent" / "managed-installation.json"
        )
        installation = json.loads(installation_path.read_bytes())
        artifact = json.loads(installation["claim"]["artifact_content"])
        endpoints = {}
        for item in ordered_profiles:
            binding = states[item.profile_id]["issued"]["window"]["binding"]
            inbound = next(
                row
                for row in artifact["inbounds"]
                if row["tag"] == binding["inbound_tag"]
            )
            credential = next(
                row
                for row in inbound["settings"]["clients"]
                if row["email"] == binding["counter_identity"]
            )
            endpoints[item.profile_id] = (inbound["port"], credential["id"])
        purchased = next(
            item for item in ordered_profiles if item.provision_task_id > 0
        )
        target = EchoTarget()
        stack.callback(target.close)
        tls = InstalledTlsEndpoints(
            endpoints,
            Path(registry_policy["certificates"][0]["path"]),
        )
        client = BoundStockClient(
            root, stock, tls, purchased.profile_id, "127.0.0.2", stack
        )
        connection = client.connect(target.port)
        stack.callback(connection.close)
        roundtrip(connection, b"paid-grant-before-core-loss")
        if process.poll() is not None:
            raise AssertionError(
                "native_core_loss_agent_exited_before_injection:"
                + (root / "window-batch-agent.log").read_text().strip()
            )
        freeze_intent_started = time.monotonic()
        profile_paths = {
            item.profile_id: (
                directory
                / "managed-window-profiles"
                / str(item.profile_id)
                / "managed-window-cycle.json"
            )
            for item in ordered_profiles
        }
        deadline = freeze_intent_started + 10
        while time.monotonic() < deadline:
            profile_states = {
                profile_id: json.loads(path.read_bytes())
                for profile_id, path in profile_paths.items()
            }
            if all(
                state.get("freeze_intent") is True
                for state in profile_states.values()
            ):
                break
            if process.poll() is not None:
                raise AssertionError(
                    "native_managed_freeze_intent_agent_exited"
                )
            time.sleep(0.02)
        else:
            raise AssertionError("native_managed_freeze_intent_not_durable")
        if failure_point == "supervisor_crash":
            os.kill(process.pid, signal.SIGKILL)
        else:
            child_pid = _managed_child_pid(
                process, Path(registry_policy["binary"]), root
            )
            os.kill(child_pid, signal.SIGKILL)
        exit_code = process.wait(timeout=60)
        if exit_code == 0:
            raise AssertionError("native_core_loss_agent_reported_success")
        if (
            failure_point == "supervisor_crash"
            and exit_code != -signal.SIGKILL
        ):
            raise AssertionError("native_managed_supervisor_not_sigkilled")
        crash_elapsed = time.monotonic() - freeze_intent_started
        if failure_point == "supervisor_crash" and crash_elapsed >= (
            freeze_after_ms / 1000
        ):
            raise AssertionError("native_managed_crash_missed_freeze_window")
        if _managed_child_pids(Path(registry_policy["binary"]), root):
            raise AssertionError("native_core_loss_child_survived")
        if failure_point == "core_loss":
            diagnostic = (root / "window-batch-agent.log").read_text().strip()
            if diagnostic != (
                "managed_window_batch_freeze_unresolved:"
                "managed_window_control_unavailable"
            ):
                raise AssertionError("native_core_loss_error_not_reported")
        connection.settimeout(3)
        try:
            established_connection_closed = connection.recv(1) == b""
        except (OSError, TimeoutError):
            established_connection_closed = False
        if not established_connection_closed:
            raise AssertionError(
                "native_core_loss_established_connection_survived"
            )
        with socket.socket() as listener:
            listener.settimeout(0.2)
            listener_closed = (
                listener.connect_ex(
                    ("127.0.0.1", endpoints[purchased.profile_id][0])
                )
                != 0
            )
        if not listener_closed:
            raise AssertionError("native_core_loss_listener_survived")
        profile_states = []
        for item in ordered_profiles:
            state_path = profile_paths[item.profile_id]
            profile_state = json.loads(state_path.read_bytes())
            if profile_state.get("submission") or profile_state.get(
                "finality"
            ):
                raise AssertionError("native_core_loss_finality_fabricated")
            if profile_state.get("freeze_intent") is not True:
                raise AssertionError("native_managed_freeze_intent_lost")
            profile_states.append(profile_state)
        epoch_path = root / "control" / "epoch-active.json"
        epoch_before_restart = epoch_path.read_bytes()
        installation_before_restart = installation_path.read_bytes()
        if (
            failure_point == "core_loss"
            and json.loads(epoch_before_restart).get("state")
            != "open_unresolved"
        ):
            raise AssertionError("native_core_loss_epoch_not_unresolved")
        profile_snapshots = {
            profile_id: path.read_bytes()
            for profile_id, path in profile_paths.items()
        }
        restart = launch(
            command + ["-once"],
            stack,
            root / "core-loss-restart.log",
            environment=environment,
        )
        restart_exit = restart.wait(timeout=20)
        if restart_exit == 0:
            raise AssertionError("native_core_loss_restart_not_refused")
        if epoch_path.read_bytes() != epoch_before_restart:
            raise AssertionError("native_core_loss_epoch_restarted")
        if installation_path.read_bytes() != installation_before_restart:
            raise AssertionError("native_core_loss_installation_mutated")
        if any(
            path.read_bytes() != profile_snapshots[profile_id]
            for profile_id, path in profile_paths.items()
        ):
            raise AssertionError("native_managed_crash_journal_mutated")
        with socket.socket() as listener:
            listener.settimeout(0.2)
            listener_closed = (
                listener_closed
                and listener.connect_ex(
                    ("127.0.0.1", endpoints[purchased.profile_id][0])
                )
                != 0
            )
        if not listener_closed:
            raise AssertionError("native_core_loss_restart_opened_listener")
        no_finality = all(
            state.get("submission") is None and state.get("finality") is None
            for state in profile_states
        )
        return NativeManagedCrashResult(
            managed_child_exited=True,
            established_connection_closed=established_connection_closed,
            restart_refused=listener_closed,
            no_finality=no_finality,
            freeze_intent_durable=True,
        )


def _managed_child_pid(process, expected_binary: Path, root: Path) -> int:
    matches = _managed_child_pids(expected_binary, root)
    if len(matches) != 1:
        diagnostic = "unavailable"
        try:
            raw = json.loads((root / "window-batch-agent.log").read_bytes())
            value = raw.get("error", "")
            tokens = re.findall(r"managed_[a-z0-9_]+", value)
            if tokens:
                diagnostic = tokens[-1]
        except (OSError, ValueError, AttributeError, TypeError):
            pass
        raise AssertionError(
            "native_core_loss_managed_child_not_unique:"
            f"exit={process.poll()}:error={diagnostic}:matches={matches}"
        )
    return matches[0]


def _managed_child_pids(expected_binary: Path, root: Path) -> list[int]:
    expected = expected_binary.resolve(strict=True)
    settings_path = str(
        root / "managed-agent" / "managed-settings.json"
    ).encode()
    matches = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        pid = int(entry.name)
        executable = entry / "exe"
        try:
            actual = executable.resolve(strict=True)
            command_line = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if actual == expected and settings_path in command_line:
            matches.append(pid)
    return matches


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
    rollover_fault: ManagedRolloverResponseDrop | None = None,
    kill_before_api_request: bool = False,
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
            if index == 2 and max_epochs > 1 and rollover_fault is not None:
                if kill_before_api_request:
                    if not rollover_fault.wait_for_held_rollover_request(45):
                        raise AssertionError(
                            "native_rollover_request_not_held_before_api"
                        )
                elif not rollover_fault.wait_for_held_rollover(45):
                    raise AssertionError(
                        "native_rollover_response_not_held_after_commit"
                    )
                installation_state = json.loads(
                    (
                        root / "managed-agent" / "managed-installation.json"
                    ).read_bytes()
                )
                pending = installation_state.get("pending_rollover") or {}
                submission = pending.get("submission")
                if not submission:
                    raise AssertionError(
                        "native_rollover_submission_not_durable_before_http"
                    )
                pending_before_outage = compact(pending, canonical=True)
                if kill_before_api_request and (
                    rollover_fault.rollover_responses()
                    or any(
                        endpoint == "rollover" and status != 0
                        for _, endpoint, status in rollover_fault.events()
                    )
                ):
                    raise AssertionError(
                        "native_rollover_api_mutated_before_request_replay"
                    )
                process.kill()
                process.wait(timeout=5)
                if kill_before_api_request:
                    rollover_fault.release_held_rollover_request()
                else:
                    rollover_fault.release_held_rollover()
                recovery_log = root / "successor-agent.log"
                recovery_log.unlink()
                process = launch(
                    command,
                    stack,
                    recovery_log,
                    environment=environment,
                )
                if not kill_before_api_request:
                    rollover_fault.set_api_outage(True)
                    outage_exit = process.wait(timeout=25)
                    if outage_exit == 0:
                        raise AssertionError(
                            "native_rollover_accepted_during_api_outage"
                        )
                    outage_state = json.loads(
                        (
                            root
                            / "managed-agent"
                            / "managed-installation.json"
                        ).read_bytes()
                    )
                    outage_pending = outage_state.get("pending_rollover") or {}
                    if compact(
                        outage_pending, canonical=True
                    ) != pending_before_outage or outage_state.get(
                        "epoch_history", []
                    ) != installation_state.get("epoch_history", []):
                        raise AssertionError(
                            "native_rollover_outage_changed_durable_intent"
                        )
                    if (
                        "POST",
                        "rollover",
                        503,
                    ) not in rollover_fault.events():
                        raise AssertionError(
                            "native_rollover_api_outage_not_exercised"
                        )
                    rollover_fault.set_api_outage(False)
                    recovery_log.unlink()
                    process = launch(
                        command,
                        stack,
                        recovery_log,
                        environment=environment,
                    )
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
