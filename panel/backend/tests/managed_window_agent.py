"""Owned native window cycle, actual stock TLS traffic and finality replay."""

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
class NativeWindowResult:
    window_id: str
    grant_id: int
    epoch: str
    upload_bytes: int
    download_bytes: int
    receipt_sha256: str
    admission_sha256: str
    replay_unchanged: bool
    child_stopped: bool


def wait_native_window(root, process, profile_id, timeout):
    deadline = time.monotonic() + timeout
    cycle_path = root / "managed-agent" / "managed-window-cycle.json"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            diagnostic = (root / "window-agent.log").read_text().strip()
            safe_code = (
                diagnostic
                if re.fullmatch(r"managed_[a-z_]+", diagnostic)
                else "unclassified"
            )
            raise AssertionError(
                "native_window_agent_exited_before_admit:" + safe_code
            )
        if cycle_path.exists():
            cycle = json.loads(cycle_path.read_bytes())
            if cycle.get("issued") and cycle.get("admission"):
                connection = UnixHTTP(root / "control" / "control.sock")
                try:
                    connection.request("GET", "/v1/observe")
                    response = connection.getresponse()
                    observation = json.loads(response.read(131073))
                    if response.status == 200 and any(
                        row["phase"] == "open"
                        and row["totals"]["binding"]["profile_id"]
                        == profile_id
                        for row in observation["profiles"]
                    ):
                        return cycle
                except (OSError, ValueError):
                    pass
                finally:
                    connection.close()
        time.sleep(0.02)
    raise AssertionError("native_window_admission_timeout")


def run_native_window_cycle(
    root: Path,
    runtime_binary: Path,
    managed_registry: dict,
    installation_id: int,
    profile_id: int,
    api_url: str,
    node: dict,
    binaries: Path,
    *,
    freeze_after_ms: int,
    payload: bytes,
) -> NativeWindowResult:
    assert freeze_after_ms > 0 and payload, "native_window_fixture_capacity"
    registry = {
        **managed_registry,
        "installation_id": installation_id,
        "window_cycle": {
            "enabled": True,
            "profile_id": profile_id,
            "generation": 0,
            "request_key": "native-window-" + str(installation_id),
            "requested_bytes": 1024,
            "freeze_after_ms": freeze_after_ms,
            "operation_timeout_ms": 5000,
            "retry_interval_ms": 100,
            "max_attempts": 3,
            "require_admission_receipt": True,
        },
    }
    config = {
        "enabled": True,
        "api_url": api_url,
        "node_code": node["node"]["code"],
        "state_directory": str(root / "unused-stock-state"),
        "managed_installation": registry,
        "poll_interval_ms": 300,
        "http_timeout_ms": 15000,
        "max_response_bytes": 2097152,
        "max_idle_connections": 2,
        "page_size": 8,
        "max_pages_per_poll": 2,
    }
    config_path = root / "window-agent-config.json"
    private_write(config_path, compact(config))
    environment = {**os.environ, "PAPILIO_NODE_KEY": node["agent_key"]}
    command = [str(runtime_binary), "-config", str(config_path), "-once"]
    with ExitStack() as stack:
        stock = stage_stock(
            root, binaries / "xray", binaries.parent / "artifacts.json"
        )
        process = launch(
            command, stack, root / "window-agent.log", environment=environment
        )
        cycle = wait_native_window(root, process, profile_id, 20)
        assert cycle.get("admission") is not None, (
            "native_window_admission_not_durable"
        )
        admission = cycle["admission"]
        assert (
            digest(admission["original_receipt"].encode())
            == admission["receipt"]["receipt_sha256"]
            and admission["admission"]["window_sha256"]
            == cycle["issued"]["window_sha256"]
            and admission["admission"]["budget_enforced"]
            and admission["admission"]["deadline_enforced"]
            and admission["admission"]["historical_only"]
            and not admission["admission"]["api_authority"]
        ), "native_window_admission_binding_invalid"
        installation = json.loads(
            (root / "managed-agent" / "managed-installation.json").read_bytes()
        )
        artifact = installation["claim"]["artifact_content"]
        assert (
            digest(artifact.encode())
            == installation["claim"]["expectation"]["artifact_sha256"]
        ), "native_window_artifact_changed"
        binding = cycle["issued"]["window"]["binding"]
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
        assert process.wait(timeout=30) == 0, "native_window_cycle_failed"
        cycle_path = root / "managed-agent" / "managed-window-cycle.json"
        before = cycle_path.read_bytes()
        completed = json.loads(before)
        assert completed.get("finality") is not None, (
            "native_window_finality_not_durable"
        )
        submission = completed["submission"]
        assert (
            digest(submission["original_receipt"].encode())
            == submission["receipt"]["snapshot_sha256"]
        ), "native_window_original_receipt_changed"
        settings = root / "managed-agent" / "managed-settings.json"
        settings_identity = (
            settings.stat().st_ino,
            settings.stat().st_mtime_ns,
        )
        assert not (root / "control" / "control.sock").exists(), (
            "native_window_owned_child_not_stopped"
        )
        replay = launch(
            command,
            stack,
            root / "window-agent-replay.log",
            environment=environment,
        )
        assert replay.wait(timeout=10) == 0, (
            "native_window_cycle_replay_failed"
        )
        unchanged = (
            cycle_path.read_bytes() == before
            and (settings.stat().st_ino, settings.stat().st_mtime_ns)
            == settings_identity
            and not (root / "control" / "control.sock").exists()
        )
        with socket.socket() as check:
            check.settimeout(0.1)
            child_stopped = (
                check.connect_ex(("127.0.0.1", inbound["port"])) != 0
            )
        assert unchanged and child_stopped, "native_window_replay_relaunched"
        finality = completed["finality"]
        return NativeWindowResult(
            finality["window_id"],
            finality["grant_id"],
            finality["acceptance"]["epoch"],
            finality["upload_bytes"],
            finality["download_bytes"],
            submission["receipt"]["snapshot_sha256"],
            admission["receipt"]["receipt_sha256"],
            unchanged,
            child_stopped,
        )
