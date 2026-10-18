"""Owned real node agent and managed CLOSED startup, never a synthetic ACK."""

import hashlib
import json
import os
import re
import select
import subprocess
import threading
import time
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

from tests.managed_ip_agent import launch, private_write


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
        "max_records": 24,
        "max_record_bytes": 16384,
        "max_validity_ms": 120000,
        "transaction_timeout_ms": 5000,
        "max_epoch_seals": 1,
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
            assert os.getloadavg()[0] <= 8, (
                "native_closed_diagnostic_load_guard"
            )
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
            + (
                safe_error
                if safe_error in known
                or re.fullmatch(r"managed_[a-z0-9_]{1,90}", safe_error)
                else "unclassified"
            )
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


def managed_child_pid(runtime_pid: int, executable: Path) -> int:
    """Find the managed child directly owned by one runtime process."""
    tasks_path = Path(f"/proc/{runtime_pid}/task")
    expected = executable.resolve()
    for task in tasks_path.iterdir():
        try:
            children = (task / "children").read_text().split()
        except FileNotFoundError:
            continue
        for child in children:
            child_path = Path(f"/proc/{child}")
            try:
                actual = (child_path / "exe").resolve()
                arguments = (child_path / "cmdline").read_bytes().split(b"\0")
            except FileNotFoundError:
                continue
            if actual == expected and b"--run" in arguments:
                return int(child)
    raise AssertionError("managed_runtime_child_not_found")


def wait_for_managed_child_pid(
    runtime_pid: int, executable: Path, timeout_seconds: float
) -> int:
    """Wait for a specific owned child to appear under its runtime process."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            return managed_child_pid(runtime_pid, executable)
        except (AssertionError, FileNotFoundError):
            time.sleep(0.01)
    raise AssertionError("managed_runtime_child_start_timeout")


def wait_for_process_exit(process_id: int, timeout_seconds: float) -> bool:
    """Wait on the kernel process handle instead of inferring from a delay."""
    process_fd = os.pidfd_open(process_id)
    try:
        return wait_for_process_exit_handle(process_fd, timeout_seconds)
    finally:
        os.close(process_fd)


def wait_for_process_exit_handle(
    process_fd: int, timeout_seconds: float
) -> bool:
    """Wait for exit on a pidfd opened before a deliberately induced crash."""
    poller = select.poll()
    poller.register(process_fd, select.POLLIN)
    return bool(poller.poll(round(timeout_seconds * 1000)))


def prepare_native_closed_installation(
    root: Path,
    runtime_binary: Path,
    registry: dict,
    id: int,
    api_url: str,
    node: dict,
    run_id: str,
    *,
    once: bool,
):
    """Prepare one isolated native runtime process for recovery acceptance."""
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
    path = root / f"agent-config-{run_id}.json"
    private_write(path, compact(config))
    command = [str(runtime_binary), "-config", str(path)]
    if once:
        command.append("-once")
    environment = {**os.environ, "PAPILIO_NODE_KEY": node["agent_key"]}
    return command, environment


class ManagedAcknowledgementProxy:
    """Drop the first committed ACK response and forward its replay."""

    def __init__(self, upstream_url: str):
        self.upstream_url = upstream_url.rstrip("/")
        self.first_ack_received = threading.Event()
        self.first_ack_upstream_completed = threading.Event()
        self.release_first_ack = threading.Event()
        self.first_ack_response_dropped = threading.Event()
        self.replayed_ack_accepted = threading.Event()
        self.lock = threading.Lock()
        self.ack_payloads: list[bytes] = []
        self.ack_upstream_errors: list[str] = []
        self.ack_upstream_statuses: list[int] = []
        self.ack_statuses: list[int] = []
        self.ack_responses: list[dict] = []
        self.server = self._server()
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            name="managed-ack-proxy",
            daemon=True,
        )

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.release_first_ack.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        assert not self.thread.is_alive(), "managed_ack_proxy_cleanup_failed"

    def _server(self) -> ThreadingHTTPServer:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: object) -> None:
                pass

            def do_GET(self) -> None:
                self.forward()

            def do_POST(self) -> None:
                self.forward()

            def forward(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                payload = self.rfile.read(length)
                is_ack = (
                    self.command == "POST"
                    and "/managed-installations/" in self.path
                    and self.path.endswith("/acknowledge")
                )
                attempt = 0
                if is_ack:
                    with owner.lock:
                        owner.ack_payloads.append(payload)
                        attempt = len(owner.ack_payloads)
                    if attempt == 1:
                        owner.first_ack_received.set()

                headers = {
                    name: value
                    for name, value in self.headers.items()
                    if name.lower()
                    not in {
                        "connection",
                        "content-length",
                        "host",
                        "keep-alive",
                        "proxy-authorization",
                        "proxy-connection",
                        "te",
                        "trailers",
                        "transfer-encoding",
                        "upgrade",
                    }
                }
                try:
                    with httpx.Client(timeout=15, trust_env=False) as client:
                        response = client.request(
                            self.command,
                            owner.upstream_url + self.path,
                            content=payload,
                            headers=headers,
                        )
                except httpx.HTTPError as error:
                    if is_ack:
                        with owner.lock:
                            owner.ack_upstream_errors.append(
                                type(error).__name__
                            )
                    self.send_response(502)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return

                if is_ack:
                    with owner.lock:
                        owner.ack_upstream_statuses.append(
                            response.status_code
                        )
                    if attempt == 1:
                        owner.first_ack_upstream_completed.set()
                        owner.release_first_ack.wait(timeout=20)
                        self.close_connection = True
                        owner.first_ack_response_dropped.set()
                        return

                self.send_response(response.status_code)
                self.send_header("Content-Length", str(len(response.content)))
                content_type = response.headers.get("content-type")
                if content_type:
                    self.send_header("Content-Type", content_type)
                self.end_headers()
                self.wfile.write(response.content)
                self.wfile.flush()
                if is_ack:
                    with owner.lock:
                        owner.ack_statuses.append(response.status_code)
                        owner.ack_responses.append(response.json())
                    if attempt > 1:
                        owner.replayed_ack_accepted.set()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        return server
