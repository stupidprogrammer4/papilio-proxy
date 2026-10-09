"""Owned real node agent and managed CLOSED startup, never a synthetic ACK."""

import hashlib
import json
import os
import subprocess
from contextlib import ExitStack
from pathlib import Path

from tests.managed_ip_agent import launch


def compact(value, *, canonical=False):
    return json.dumps(
        value, sort_keys=canonical, separators=(",", ":"), ensure_ascii=False
    ).encode()


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def actual_registry(root: Path, inputs: Path, binary: Path):
    materials = [
        {
            "path": str(inputs / filename),
            "sha256": digest((inputs / filename).read_bytes()),
        }
        for filename in ("cert.pem", "key.pem")
    ]
    enforcement = {
        "max_read_reservation_bytes": 32,
        "max_residual_bytes": 1048576,
        "max_concurrent_reservations": 8,
        "read_lease_ms": 1500,
        "reservation_wait_ms": 500,
        "max_clock_skew_ms": 1000,
        "contention_mode": "close_profile",
    }
    windows = {
        "max_windows": 8,
        "max_records": 16,
        "max_record_bytes": 16384,
        "max_validity_ms": 120000,
        "transaction_timeout_ms": 5000,
    }
    component = {
        "remote_read_buffer_bytes": 65536,
        "tcp_listener_send_buffer_bytes": 4096,
        "tcp_listener_min_effective_send_buffer_bytes": 4096,
        "tcp_listener_max_effective_send_buffer_bytes": 16384,
        "max_certificate_bytes": 65536,
        "max_executable_bytes": 268435456,
        "max_json_depth": 32,
        "max_document_bytes": 1048576,
        "max_control_concurrency": 4,
        "max_outbound_connections": 16,
        "dial_timeout_ms": 3000,
        "max_profiles": 16,
        "max_sessions": 16,
        "max_operations": 128,
        "max_barriers": 8,
        "max_snapshot_bytes": 131072,
        "max_control_bytes": 65536,
        "drain_timeout_ms": 4000,
        "control_timeout_ms": 3000,
    }
    policy = {
        "executable_sha256": digest(binary.read_bytes()),
        "materials_sha256": digest(compact(materials)),
        "enforcement_sha256": digest(compact(enforcement, canonical=True)),
        "window_policy_sha256": digest(compact(windows, canonical=True)),
    }
    registry = {
        "enabled": True,
        "installation_id": 0,
        "binary": str(binary),
        "input_root": str(inputs),
        "control_root": str(root / "control"),
        "state_directory": str(root / "managed-agent"),
        "certificates": materials,
        "component_policy": component,
        "enforcement_policy": enforcement,
        "window_policy": windows,
        "max_settings_bytes": 2097152,
        "max_settings_depth": 40,
        "max_executable_bytes": 268435456,
        "max_receipt_bytes": 131072,
        "max_journal_bytes": 4194304,
        "startup_timeout_ms": 15000,
        "poll_interval_ms": 300,
        "stop_timeout_ms": 8000,
    }
    return {"trusted_api_policy": policy, "registry": registry}


def run_native_closed_installation(
    root: Path,
    runtime_binary: Path,
    registry: dict,
    id: int,
    api_url: str,
    node: dict,
):
    config = {
        "enabled": True,
        "api_url": api_url,
        "node_code": node["node"]["code"],
        "state_directory": str(root / "unused-stock-state"),
        "managed_installation": {**registry, "installation_id": id},
        "poll_interval_ms": 300,
        "http_timeout_ms": 15000,
        "max_response_bytes": 2097152,
        "max_idle_connections": 2,
        "page_size": 8,
        "max_pages_per_poll": 2,
    }
    path = root / "agent-config.json"
    path.write_bytes(compact(config))
    path.chmod(0o600)
    environment = {**os.environ, "PAPILIO_NODE_KEY": node["agent_key"]}
    assert os.getloadavg()[0] <= 8, "native_closed_agent_load_guard"
    with ExitStack() as stack:
        process = launch(
            [str(runtime_binary), "-config", str(path), "-once"],
            stack,
            root / "agent-output.log",
            environment=environment,
        )
        exit_code = process.wait(timeout=35)
    if exit_code:
        safe_error = (root / "agent-output.log").read_text().strip()
        if safe_error == "managed_child_exited":
            assert os.getloadavg()[0] <= 8, "native_closed_diagnostic_load_guard"
            checked = subprocess.run(
                [
                    registry["binary"],
                    "--check",
                    "--config",
                    str(root / "managed-agent" / "managed-settings.json"),
                    "--max-config-bytes",
                    str(registry["max_settings_bytes"]),
                    "--max-config-depth",
                    str(registry["max_settings_depth"]),
                ],
                capture_output=True,
                timeout=20,
                env={
                    key: value
                    for key, value in environment.items()
                    if key != "PAPILIO_NODE_KEY"
                },
            )
            diagnostic = json.loads(checked.stdout)
            if checked.returncode:
                safe_error = diagnostic.get("error", "unclassified")
        known = {
            "managed_expected_bindings_invalid",
            "managed_closed_startup_unavailable",
            "managed_child_exited",
            "managed_expected_windows_invalid",
            "managed_expected_enforcement_invalid",
            "managed_binary_reference_mismatch",
            "managed_journal_capacity",
            "managed_child_cleanup_unresolved",
            "managed_settings_invalid",
            "managed_policy_invalid",
            "managed_build_dependency_unverified",
            "managed_build_reference_mismatch",
            "managed_document_digest_mismatch",
            "managed_bindings_digest_mismatch",
            "managed_materials_digest_mismatch",
            "managed_document_unavailable",
            "managed_native_config_invalid",
            "managed_dispatcher_overlay_invalid",
            "managed_native_init_failed",
            "managed_core_start_failed",
            "managed_listener_budget_unobserved",
            "managed_listener_budget_mismatch",
            "managed_epoch_recovery_unresolved",
            "managed_recovery_unresolved",
            "managed_control_path_owned",
            "managed_shutdown_unresolved",
            "managed_prototype_unavailable",
        }
        raise AssertionError(
            "native_closed_agent_failed:"
            + (safe_error if safe_error in known else "unclassified")
        )
    journal = root / "managed-agent" / "managed-installation.json"
    state = json.loads(journal.read_bytes())
    receipt = state["acknowledgement"]
    startup = json.loads(receipt["original_receipt"])
    acceptance = state["acceptance"]
    assert (
        state["installation_id"] == id and acceptance["installation_id"] == id
    )
    assert startup["historical_only"] and not startup["api_authority"]
    assert not acceptance["admission_available"]
    assert startup["epoch"] == acceptance["process_epoch"]
    assert (
        digest(receipt["original_receipt"].encode())
        == acceptance["receipt_sha256"]
    )
    assert all(
        profile["phase"] == "enrolled_closed"
        and profile["resources"] == 0
        and profile["active_operations"] == 0
        for profile in startup["profiles"]
    )
    assert journal.stat().st_mode & 0o077 == 0
    # The -once operation has joined and stopped its real child. A durable
    # historical startup observation must not become current runtime readiness.
    return {
        "actual_agent_claim": True,
        "actual_child_closed_receipt": True,
        "native_exact_ack": True,
        "historical_only": True,
        "paid_activation_unavailable": True,
    }
