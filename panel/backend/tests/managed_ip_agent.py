"""Actual native assignment/IP leases; isolated component is NOT API-installed.

All application decisions come from the real authenticated HTTP API. The relay
only forwards requests or deliberately drops them to model a network partition.
Local windows have neither native grant authority nor strict budget/deadline
capability. Source addresses are TCP peer addresses, never device identities.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import http.client
import ipaddress
import json
import os
import select
import signal
import socket
import subprocess
import threading
import time
from collections import deque
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx

from src.modules.network.configurations.app.counter_identity import (
    profile_counter_identity,
)
from tests.core_provisioning_agent import _data, _stop_core
from tests.scheduler_runtime import _exercise_native_runtime


def encoded(value: object, *, canonical: bool = False) -> bytes:
    return json.dumps(
        value, separators=(",", ":"), ensure_ascii=False, sort_keys=canonical
    ).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def private_write(path: Path, content: bytes) -> None:
    with path.open("xb") as output:
        path.chmod(0o600)
        output.write(content)


def stage_stock(directory: Path, source: Path, manifest: Path) -> Path:
    reference = next(
        row
        for row in json.loads(manifest.read_bytes())
        if row["name"] == "xray"
    )
    assert reference["version"] == "26.3.27", (
        "native_ip_stock_reference_changed"
    )
    assert 0 < source.stat().st_size <= 268435456, "native_ip_stock_capacity"
    target = directory / "owned-stock-xray"
    checksum = hashlib.sha256()
    with source.open("rb") as reader, target.open("xb") as writer:
        target.chmod(0o700)
        while chunk := reader.read(65536):
            checksum.update(chunk)
            writer.write(chunk)
    assert checksum.hexdigest() == reference["binary_sha256"], (
        "native_ip_stock_hash_unverified"
    )
    assert os.getloadavg()[0] <= 8, "owned_ip_load_gate"
    version = subprocess.run(
        [str(target), "version"], capture_output=True, timeout=5, check=False
    )
    assert (
        version.returncode == 0
        and len(version.stdout) <= 8192
        and reference["version"].encode() in version.stdout
    ), "native_ip_stock_version_unverified"
    return target


def stop_owned(process: subprocess.Popen) -> None:
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(3)
    assert process.poll() is not None, "owned_ip_child_cleanup_failed"


def launch(command, stack: ExitStack, log: Path, *, environment=None):
    assert os.getloadavg()[0] <= 8, "owned_ip_load_gate"
    stream = stack.enter_context(log.open("xb"))
    log.chmod(0o600)
    process = subprocess.Popen(
        command,
        env=environment,
        stdout=stream,
        stderr=stream,
        start_new_session=True,
    )
    stack.callback(stop_owned, process)
    return process


def agent_config(directory, binaries, base_url, node):
    return {
        "enabled": True,
        "api_url": base_url,
        "node_code": node["node"]["code"],
        "state_directory": str(directory),
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


class NativeRelay:
    """Bounded forwarding transport, with a test-owned drop-only partition."""

    def __init__(self, base_url: str, node_codes: tuple[str, ...]):
        owner = self
        self.partition = threading.Event()
        self.capacity = threading.BoundedSemaphore(8)
        self.diagnostics = deque(maxlen=64)
        aliases = dict(zip(node_codes, ("A", "B"), strict=True))
        self.client = httpx.Client(
            base_url=base_url,
            timeout=2,
            trust_env=False,
            follow_redirects=False,
        )

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

            def do_POST(self):
                started = time.monotonic()
                node_alias = aliases.get(self.path.split("/")[3], "other")
                self.connection.settimeout(3)
                if owner.partition.is_set() or not owner.capacity.acquire(
                    blocking=False
                ):
                    self.close_connection = True
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    assert 0 < length <= 2048, "relay_request_capacity"
                    assert self.path.startswith(
                        "/v1/nodes/"
                    ) and self.path.endswith("/ip-admission"), "relay_scope"
                    response = owner.client.post(
                        self.path,
                        headers={
                            "X-Papilio-Node-Key": self.headers.get(
                                "X-Papilio-Node-Key", ""
                            ),
                            "Content-Type": "application/json",
                        },
                        content=self.rfile.read(length),
                    )
                    reason = response.json().get("data", {}).get("reason")
                    safe_reason = (
                        reason
                        if reason
                        in {
                            "ip_admitted",
                            "limit_disabled",
                            "entitlement_inactive",
                            "quota_exhausted",
                            "ip_blocked",
                            "ip_limit_exceeded",
                            "ip_policy_draining",
                        }
                        else "other"
                    )
                    owner.diagnostics.append(
                        {
                            "node": node_alias,
                            "status": response.status_code,
                            "reason": safe_reason,
                            "seconds": round(time.monotonic() - started, 3),
                        }
                    )
                    assert len(response.content) <= 65536, (
                        "relay_response_capacity"
                    )
                    self.send_response(response.status_code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header(
                        "Content-Length", str(len(response.content))
                    )
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(response.content)
                except (OSError, ValueError, httpx.HTTPError) as error:
                    owner.diagnostics.append(
                        {
                            "node": node_alias,
                            "error": type(error).__name__,
                            "seconds": round(time.monotonic() - started, 3),
                        }
                    )
                    self.close_connection = True
                finally:
                    owner.capacity.release()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = False
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)
        self.client.close()
        assert not self.thread.is_alive(), "relay_cleanup_failed"


class EchoTarget:
    def __init__(self):
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(16)
        self.listener.settimeout(0.1)
        self.port = self.listener.getsockname()[1]
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.sockets: set[socket.socket] = set()
        self.workers: list[threading.Thread] = []
        self.capacity = threading.BoundedSemaphore(16)
        self.thread = threading.Thread(target=self.accept, daemon=True)
        self.thread.start()

    def accept(self):
        while not self.stop.is_set():
            try:
                connection, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            if not self.capacity.acquire(blocking=False):
                connection.close()
                continue
            connection.settimeout(2)
            with self.lock:
                self.sockets.add(connection)
                worker = threading.Thread(
                    target=self.serve, args=(connection,), daemon=True
                )
                self.workers.append(worker)
            worker.start()

    def serve(self, connection):
        try:
            while not self.stop.is_set():
                try:
                    payload = connection.recv(4096)
                except socket.timeout:
                    continue
                if not payload:
                    return
                connection.sendall(payload)
        except OSError:
            pass
        finally:
            connection.close()
            with self.lock:
                self.sockets.discard(connection)
            self.capacity.release()

    def close(self):
        self.stop.set()
        self.listener.close()
        with self.lock:
            sockets = list(self.sockets)
        for connection in sockets:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        self.thread.join(2)
        for worker in self.workers:
            worker.join(3)
        assert not self.thread.is_alive() and all(
            not item.is_alive() for item in self.workers
        ), "echo_cleanup_failed"


class UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost", timeout=5)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(5)
        self.sock.connect(str(self.path))


@dataclass(frozen=True, slots=True)
class InstalledTlsEndpoints:
    endpoints: dict[int, tuple[int, str]]
    certificate: Path


def native_endpoints(bundle, certificate):
    assert len(bundle["filenames"]) == 1, "native_stock_requires_merged_bundle"
    payload = (Path(bundle["directory"]) / bundle["filenames"][0]).read_bytes()
    assert (
        len(payload) <= 1048576
        and digest(payload) == bundle["artifact_sha256"][0]
    ), "native_stock_artifact_digest_changed"
    document = json.loads(payload)
    endpoints = {}
    for member in bundle["memberships"]:
        counter = profile_counter_identity(
            member["profile_id"], member["generation"]
        )
        inbound = next(
            row
            for row in document["inbounds"]
            if row["tag"] == "node-" + str(member["configuration_id"])
        )
        client = next(
            row
            for row in inbound["settings"]["clients"]
            if row["email"] == counter
        )
        assert member["presence"] == "present" and not client.get("flow"), (
            "native_stock_profile_unavailable"
        )
        endpoints[member["profile_id"]] = (inbound["port"], client["id"])
    return InstalledTlsEndpoints(endpoints, certificate)


class AssignedManagedPrototype:
    def __init__(self, root, binary, bundle, node, relay_url, inputs, stack):
        self.root = root
        root.mkdir(mode=0o700)
        assert len(bundle["filenames"]) == 1, (
            "lease_probe_requires_merged_bundle"
        )
        artifact = Path(bundle["directory"]) / bundle["filenames"][0]
        payload = artifact.read_bytes()
        assert (
            len(payload) <= 1048576
            and digest(payload) == bundle["artifact_sha256"][0]
        ), "native_artifact_digest_changed"
        # Raw JSON is embedded unchanged, except its insignificant outer space.
        # The backend artifact hash remains independently verified above.
        document_payload = payload.strip()
        document = json.loads(document_payload)
        assert document["log"] == {"loglevel": "none"}, (
            "native_log_policy_not_preserved"
        )
        memberships = bundle["memberships"]
        assert memberships and bundle["membership_sha256"], (
            "native_installed_membership_missing"
        )
        bindings = []
        self.endpoints: dict[int, tuple[int, str]] = {}
        for member in memberships:
            assert member["presence"] == "present" and member[
                "artifact_sha256"
            ] == digest(payload), "native_membership_not_installed"
            identity = profile_counter_identity(
                member["profile_id"], member["generation"]
            )
            inbound = next(
                item
                for item in document["inbounds"]
                if item["tag"] == "node-" + str(member["configuration_id"])
            )
            client = next(
                item
                for item in inbound["settings"]["clients"]
                if item["email"] == identity
            )
            assert not client.get("flow"), (
                "native_vision_not_supported_no_rewrite"
            )
            binding = {
                "profile_id": member["profile_id"],
                "generation": member["generation"],
                "configuration_id": member["configuration_id"],
                "configuration_revision": member["configuration_revision"],
                "counter_identity": identity,
                "inbound_tag": inbound["tag"],
            }
            bindings.append(binding)
            self.endpoints[member["profile_id"]] = (
                inbound["port"],
                client["id"],
            )
        materials = [
            {"path": str(path), "sha256": digest(path.read_bytes())}
            for path in (inputs / "cert.pem", inputs / "key.pem")
        ]
        window_bindings = [
            {
                "binding": binding,
                "membership_sha256": bundle["membership_sha256"],
                "profile_sha256": digest(encoded(member, canonical=True)),
            }
            for binding, member in zip(bindings, memberships, strict=True)
        ]
        self.installation = {
            "materials_sha256": digest(encoded(materials)),
            "executable_sha256": digest(binary.read_bytes()),
            "document_sha256": digest(document_payload),
            "bindings_sha256": digest(encoded(bindings)),
        }
        self.window_bindings = window_bindings
        self.certificate = inputs / "cert.pem"
        self.journal = root / "journal"
        settings = {
            "enabled": True,
            "accounting_mode": "window_component",
            "input_root": str(inputs),
            "control_root": str(self.journal),
            "installation": self.installation,
            "bindings": bindings,
            "certificates": materials,
            "internal_targets": [],
            "window_policy": {
                "max_windows": 8,
                "max_records": 16,
                "max_record_bytes": 16384,
                "max_validity_ms": 120000,
                "transaction_timeout_ms": 5000,
            },
            "window_bindings": window_bindings,
            "ip_bindings": [
                {"subscription_id": member["subscription_id"], **binding}
                for member, binding in zip(
                    memberships, window_bindings, strict=True
                )
            ],
            "ip_admission": {
                "mode": "api_presence_lease",
                "api_url": relay_url,
                "node_code": node["node"]["code"],
                "node_key": node["agent_key"],
                "request_timeout_ms": 800,
                "max_response_bytes": 65536,
                "max_inflight_requests": 4,
                "renew_before_ms": 300,
                "join_timeout_ms": 1500,
                "max_bindings": 8,
            },
            "policy": {
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
                "max_profiles": 8,
                "max_sessions": 16,
                "max_operations": 128,
                "max_barriers": 8,
                "max_snapshot_bytes": 131072,
                "max_control_bytes": 65536,
                "drain_timeout_ms": 4000,
                "control_timeout_ms": 3000,
            },
        }
        config = root / "settings.json"
        private_write(
            config,
            encoded(settings)[:-1] + b',"document":' + document_payload + b"}",
        )
        assert os.getloadavg()[0] <= 8, "owned_ip_load_gate"
        stderr = stack.enter_context((root / "stderr.log").open("xb"))
        (root / "stderr.log").chmod(0o600)
        self.process = subprocess.Popen(
            [
                str(binary),
                "--run",
                "--config",
                str(config),
                "--max-config-bytes",
                "2097152",
                "--max-config-depth",
                "40",
            ],
            stdout=subprocess.PIPE,
            stderr=stderr,
            start_new_session=True,
        )
        stack.callback(stop_owned, self.process)
        assert self.process.stdout is not None
        ready, _, _ = select.select([self.process.stdout], [], [], 15)
        assert ready, "native_managed_child_start_timeout"
        output = self.process.stdout.readline(8193)
        assert len(output) <= 8192, "native_managed_child_output_capacity"
        response = json.loads(output)
        if response.get("state") != "isolated_prototype_running":
            safe = response.get("error")
            code = (
                safe
                if safe
                in {
                    "managed_settings_invalid",
                    "managed_policy_invalid",
                    "managed_document_unavailable",
                    "managed_native_config_invalid",
                    "managed_native_init_failed",
                    "managed_core_start_failed",
                    "managed_listener_budget_unobserved",
                    "managed_listener_budget_mismatch",
                }
                else "unclassified"
            )
            raise AssertionError("native_managed_child_not_ready:" + code)
        self.epoch = response["epoch"]
        status, observation = self.request("GET", "/v1/observe")
        assert status == 200 and all(
            row["phase"] == "enrolled_closed"
            for row in observation["profiles"]
        ), "native_managed_window_not_initially_closed"
        for binding in window_bindings:
            issued = dt.datetime.now(dt.UTC)

            def stamp(value):
                return value.isoformat(timespec="microseconds").replace(
                    "+00:00", "Z"
                )

            grant = {
                "grant_id": binding["binding"]["profile_id"],
                "window_id": uuid4().hex,
                "epoch": self.epoch,
                "installation": self.installation,
                **binding,
                "baseline_upload_bytes": 0,
                "baseline_download_bytes": 0,
                "allocated_bytes": 1000000,
                "issued_at": stamp(issued),
                "valid_until": stamp(issued + dt.timedelta(seconds=110)),
                "predecessor": None,
            }
            status, acknowledged = self.request(
                "POST", "/v1/windows/admit", grant
            )
            assert (
                status == 200
                and acknowledged["state"] == "local_component_window_admitted"
            ), "native_local_window_admit_failed"
            assert (
                acknowledged["budget_enforced"] is False
                and acknowledged["deadline_enforced"] is False
            ), "lease_probe_claimed_grant_authority"

    def request(self, method, path, body=None):
        connection = UnixHTTP(self.journal / "control.sock")
        try:
            connection.request(
                method,
                path,
                body=encoded(body) if body is not None else None,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            return response.status, json.loads(response.read(131073))
        finally:
            connection.close()


def exact(connection, count):
    result = bytearray()
    while len(result) < count:
        payload = connection.recv(count - len(result))
        if not payload:
            raise EOFError("owned_ip_connection_closed")
        result.extend(payload)
    return bytes(result)


class BoundStockClient:
    def __init__(self, root, binary, core, profile, source, stack):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            self.port = reservation.getsockname()[1]
        port, identity = core.endpoints[profile]
        document = {
            "log": {"loglevel": "none"},
            "inbounds": [
                {
                    "listen": "127.0.0.1",
                    "port": self.port,
                    "protocol": "socks",
                    "settings": {"auth": "noauth", "udp": False},
                }
            ],
            "outbounds": [
                {
                    "protocol": "vless",
                    "sendThrough": source,
                    "settings": {
                        "vnext": [
                            {
                                "address": "127.0.0.1",
                                "port": port,
                                "users": [
                                    {
                                        "id": identity,
                                        "encryption": "none",
                                        "flow": "",
                                    }
                                ],
                            }
                        ]
                    },
                    "streamSettings": {
                        "network": "tcp",
                        "security": "tls",
                        "tlsSettings": {
                            "serverName": "localhost",
                            "allowInsecure": False,
                            "certificates": [
                                {
                                    "certificateFile": str(core.certificate),
                                    "usage": "verify",
                                }
                            ],
                        },
                    },
                }
            ],
        }
        path = root / ("client-" + uuid4().hex + ".json")
        private_write(path, encoded(document))
        self.process = launch(
            [str(binary), "run", "-config", str(path)],
            stack,
            path.with_suffix(".log"),
        )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            assert self.process.poll() is None, (
                "owned_bound_stock_client_exited"
            )
            try:
                with socket.create_connection(
                    ("127.0.0.1", self.port), timeout=0.1
                ):
                    break
            except OSError:
                time.sleep(0.02)
        else:
            raise AssertionError("owned_bound_stock_client_not_ready")
        self.stack = stack

    def connect(self, target):
        connection = socket.create_connection(
            ("127.0.0.1", self.port), timeout=2
        )
        self.stack.callback(connection.close)
        connection.sendall(b"\x05\x01\x00")
        assert exact(connection, 2) == b"\x05\x00", (
            "bound_client_socks_negotiation"
        )
        address = ipaddress.ip_address("127.0.0.1")
        connection.sendall(
            b"\x05\x01\x00\x01" + address.packed + target.to_bytes(2, "big")
        )
        response = exact(connection, 4)
        assert response[:2] == b"\x05\x00", "bound_client_socks_destination"
        length = {1: 4, 4: 16}.get(response[3])
        if length is None:
            assert response[3] == 3, "bound_client_socks_address"
            length = exact(connection, 1)[0]
        exact(connection, length + 2)
        return connection


def roundtrip(connection, payload=b"owned-native-ip-lease-payload"):
    connection.sendall(payload)
    assert exact(connection, len(payload)) == payload, (
        "native_ip_known_payload"
    )


def denied(client, target):
    try:
        roundtrip(client.connect(target), b"must-not-cross-denied-ip")
    except (OSError, EOFError):
        return
    raise AssertionError("native_denied_ip_delivered")


def wait_closed(connection, seconds: float = 5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            roundtrip(connection, b"lease-recheck")
        except (OSError, EOFError):
            return
        time.sleep(0.1)
    raise AssertionError("native_ip_renewal_did_not_close")


def configure(
    api,
    subscription_id,
    *,
    max_ips,
    enabled=True,
    lease_seconds=2,
    transition_mode=None,
):
    return _data(
        api.put(
            f"/v1/admin/subscriptions/{subscription_id}/ip-limit",
            json={
                "enabled": enabled,
                "max_ips": max_ips,
                "lease_seconds": lease_seconds,
                "transition_mode": transition_mode,
                "ban_seconds": 1,
                "mode": "reject_new",
            },
        ),
        "native_ip_policy_write_failed",
    )


def wait_block_elapsed(api, subscription_id, source):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        rows = _data(
            api.get(
                f"/v1/admin/subscriptions/{subscription_id}/ip-limit/sessions",
                params={"q": source, "per_page": 16},
            ),
            "native_block_read_failed",
        )
        matching = [row for row in rows if row["source_ip"] == source]
        if matching and all(
            row["blocked_until"] is None
            or dt.datetime.fromisoformat(
                row["blocked_until"].replace("Z", "+00:00")
            )
            <= dt.datetime.now(dt.UTC)
            for row in matching
        ):
            return
        time.sleep(0.02)
    raise AssertionError("native_timed_block_did_not_elapsed")


@dataclass(frozen=True, slots=True)
class OwnedInstalledIpPresence:
    api: httpx.Client
    nodes: list[dict]
    cores: list[dict]
    subscription_id: int
    managed: list[AssignedManagedPrototype]
    stock: Path
    target: EchoTarget
    stack: ExitStack
    relay: NativeRelay


@contextmanager
def installed_ip_presence_fixture(
    directory,
    runtime_binary,
    managed_binary,
    binaries,
    base_url,
    admin_headers,
    sale,
    runtime,
    raw,
    namespace,
):
    nodes, cores = sale["nodes"], sale["cores"]
    subscription_id, request_id = (
        sale["subscription"]["id"],
        sale["request"]["id"],
    )
    with ExitStack() as stack:
        stock = stage_stock(
            directory, binaries / "xray", binaries.parent / "artifacts.json"
        )
        api = stack.enter_context(
            httpx.Client(
                base_url=base_url,
                headers=admin_headers,
                timeout=10,
                trust_env=False,
                follow_redirects=False,
            )
        )
        agents, journals = [], []
        for index, node in enumerate(nodes):
            journal = directory / ("stock-journal-" + str(index))
            journals.append(journal)
            path = directory / ("stock-agent-" + str(index) + ".json")
            config = agent_config(journal, binaries, base_url, node)
            config["binaries"]["xray"] = str(stock)
            private_write(path, encoded(config))
            agents.append(
                launch(
                    [str(runtime_binary), "-config", str(path)],
                    stack,
                    path.with_suffix(".log"),
                    environment={
                        **os.environ,
                        "PAPILIO_NODE_KEY": node["agent_key"],
                    },
                )
            )
        _exercise_native_runtime(
            raw,
            "SELECT r.state request_state,s.status subscription_status,"
            "COUNT(t.id) task_count,SUM(t.state='applied' AND "
            "t.installed_revision_id IS NOT NULL AND "
            "t.membership_sha256 IS NOT NULL AND "
            "p.applied_generation=r.generation) proof_count "
            "FROM tbl_provision_requests r "
            "JOIN tbl_subscriptions s ON s.id=r.subscription_id "
            "JOIN tbl_provision_tasks t ON t.request_id=r.id "
            "JOIN tbl_profiles p ON p.id=t.profile_id "
            "WHERE r.id=%s GROUP BY r.state,s.status",
            (request_id,),
            lambda row: (
                row["request_state"] == "active"
                and row["subscription_status"] == "active"
                and row["task_count"] == 3
                and row["proof_count"] == 3
            ),
            ("task_count", "proof_count"),
            (
                "ScanProvisioning",
                "ScanCoreProvisioning",
                "EnsureCoreProvisioning",
            ),
            owned_namespace=namespace,
        )
        tasks = _data(
            api.get(f"/v1/admin/provisioning/{request_id}/tasks"),
            "native_ip_task_read_failed",
        )
        assert len(tasks) == 3 and all(
            row["state"] == "applied" for row in tasks
        ), "native_ip_profiles_unapplied"
        replay = _data(
            api.post("/v1/admin/subscriptions", json=sale["purchase"]),
            "native_ip_paid_replay_failed",
        )
        assert replay["id"] == subscription_id, "native_ip_paid_replay_changed"
        wallet = _data(
            api.get(f"/v1/admin/payments/wallets/{sale['customer']['id']}"),
            "native_ip_wallet_read_failed",
        )
        assert wallet["balance_rial"] == 200000, (
            "native_ip_paid_replay_double_debit"
        )
        bundles = []
        target = EchoTarget()
        stack.callback(target.close)
        for core, journal, agent in zip(cores, journals, agents, strict=True):
            base = f"/v1/admin/network/cores/{core['id']}/runtime"
            state = _data(api.get(base), "native_ip_installed_state_missing")
            local = json.loads(
                (journal / str(core["id"]) / "state.json").read_bytes()
            )
            bundle = local["applied"]
            assert (
                state["observed_status"] == "running"
                and state["applied_revision_id"] == bundle["revision_id"]
            ), "native_ip_install_binding_missing"
            task_by_profile = {row["profile_id"]: row for row in tasks}
            for member in bundle["memberships"]:
                task = task_by_profile[member["profile_id"]]
                assert (
                    member["subscription_id"] == subscription_id
                    and member["generation"] == sale["request"]["generation"]
                    and member["configuration_id"] == task["configuration_id"]
                    and member["configuration_revision"]
                    == task["configuration_revision"]
                    and task["installed_revision_id"] == bundle["revision_id"]
                    and task["membership_sha256"]
                    == bundle["membership_sha256"]
                ), "native_profile_membership_binding_changed"
            bundles.append(bundle)
            endpoints = native_endpoints(
                bundle, directory / "inputs" / "cert.pem"
            )
            for profile in sorted(endpoints.endpoints):
                native_client = BoundStockClient(
                    directory, stock, endpoints, profile, "127.0.0.1", stack
                )
                connection = native_client.connect(target.port)
                roundtrip(connection, b"paid-native-stock-installation-proof")
                connection.close()
                stop_owned(native_client.process)
            _stop_core(api, base, agent)
        for agent in agents:
            stop_owned(agent)
        configure(api, subscription_id, max_ips=1)
        relay = NativeRelay(
            base_url, tuple(node["node"]["code"] for node in nodes)
        )
        stack.callback(relay.close)
        managed = [
            AssignedManagedPrototype(
                directory / ("managed-" + str(index)),
                managed_binary,
                bundle,
                node,
                relay.url,
                directory / "inputs",
                stack,
            )
            for index, (bundle, node) in enumerate(
                zip(bundles, nodes, strict=True)
            )
        ]
        try:
            yield OwnedInstalledIpPresence(
                api,
                nodes,
                cores,
                subscription_id,
                managed,
                stock,
                target,
                stack,
                relay,
            )
        except Exception:
            print(
                json.dumps(
                    {"safe_relay_diagnostics": list(relay.diagnostics)}
                ),
                flush=True,
            )
            raise


def exercise_native_managed_ip(
    directory,
    runtime_binary,
    managed_binary,
    binaries,
    base_url,
    admin_headers,
    sale,
    runtime,
    raw,
    namespace,
):
    with installed_ip_presence_fixture(
        directory,
        runtime_binary,
        managed_binary,
        binaries,
        base_url,
        admin_headers,
        sale,
        runtime,
        raw,
        namespace,
    ) as fixture:
        api = fixture.api
        nodes, cores = fixture.nodes, fixture.cores
        subscription_id = fixture.subscription_id
        managed, stock = fixture.managed, fixture.stock
        target, stack = fixture.target, fixture.stack
        relay = fixture.relay
        profile_groups = [sorted(core.endpoints) for core in managed]
        assert [len(group) for group in profile_groups] == [2, 1], (
            "native_ip_profile_topology_changed"
        )
        same_ip = [
            BoundStockClient(
                directory, stock, core, profile, "127.0.0.2", stack
            )
            for core in managed
            for profile in sorted(core.endpoints)
        ]
        connections = [client.connect(target.port) for client in same_ip]
        for connection in connections:
            roundtrip(connection)
        sessions = _data(
            api.get(
                f"/v1/admin/subscriptions/{subscription_id}/ip-limit/sessions",
                params={"state": "active", "per_page": 16},
            ),
            "native_ip_presence_read_failed",
        )
        assert (
            len(sessions) == 1 and sessions[0]["source_ip"] == "127.0.0.2"
        ), "native_peer_alias_not_observed_or_ref_duplicated"
        extra = BoundStockClient(
            directory,
            stock,
            managed[1],
            profile_groups[1][0],
            "127.0.0.3",
            stack,
        )
        denied(extra, target.port)
        connections[0].close()
        roundtrip(connections[1], b"same-ip-reference-still-live")
        roundtrip(connections[2], b"same-ip-other-node-still-live")
        connections[1].close()
        connections[2].close()
        after_last_close = _data(
            api.get(
                f"/v1/admin/subscriptions/{subscription_id}/ip-limit/sessions",
                params={"state": "active", "per_page": 16},
            ),
            "native_last_close_presence_read_failed",
        )
        assert any(
            row["source_ip"] == "127.0.0.2" for row in after_last_close
        ), "presence_ttl_falsely_treated_as_socket_release"
        connections[1] = same_ip[1].connect(target.port)
        connections[2] = same_ip[2].connect(target.port)
        roundtrip(connections[1])
        roundtrip(connections[2])
        configure(api, subscription_id, max_ips=2)
        wait_block_elapsed(api, subscription_id, "127.0.0.3")
        extra_connection = extra.connect(target.port)
        roundtrip(extra_connection)
        third = BoundStockClient(
            directory,
            stock,
            managed[0],
            profile_groups[0][0],
            "127.0.0.4",
            stack,
        )
        denied(third, target.port)
        configure(api, subscription_id, max_ips=2, enabled=False)
        wait_block_elapsed(api, subscription_id, "127.0.0.4")
        third_connection = third.connect(target.port)
        roundtrip(third_connection)
        detail = _data(
            api.get(f"/v1/admin/subscriptions/{subscription_id}/ip-limit"),
            "native_ip_effective_policy_failed",
        )
        assert (
            detail["effective_ip_policy"]["policy"]["enabled"] is False
            and detail["effective_ip_policy"]["core_enforcement_verified"]
            is False
        ), "native_api_claimed_component_enforcement"
        wrong = api.post(
            f"/v1/nodes/{nodes[0]['node']['code']}/ip-admission",
            headers={"X-Papilio-Node-Key": "owned-invalid-node-key"},
            json={
                "subscription_id": subscription_id,
                "source_ip": "127.0.0.2",
            },
        )
        assert wrong.status_code == 401, "native_invalid_node_key_admitted"
        foreign = sale["foreign_node"]
        unassigned = api.post(
            f"/v1/nodes/{foreign['node']['code']}/ip-admission",
            headers={"X-Papilio-Node-Key": foreign["agent_key"]},
            json={
                "subscription_id": subscription_id,
                "source_ip": "127.0.0.2",
            },
        )
        assert unassigned.status_code == 409, "native_unassigned_node_admitted"
        relay.partition.set()
        wait_closed(connections[1])
        wait_closed(connections[2])
        wait_closed(extra_connection)
        wait_closed(third_connection)
        denied(same_ip[0], target.port)
        relay.partition.clear()
        resumed_a = same_ip[1].connect(target.port)
        resumed_b = same_ip[2].connect(target.port)
        roundtrip(resumed_a)
        roundtrip(resumed_b)
        disabled = api.patch(
            f"/v1/admin/network/nodes/{nodes[1]['node']['id']}/enabled",
            json={"enabled": False},
        )
        assert disabled.status_code == 200, "native_node_disable_failed"
        wait_closed(resumed_b)
        denied(same_ip[2], target.port)
        roundtrip(resumed_a, b"other-node-stays-live")
        enabled = api.patch(
            f"/v1/admin/network/nodes/{nodes[1]['node']['id']}/enabled",
            json={"enabled": True},
        )
        assert enabled.status_code == 200, "native_node_resume_failed"
        resumed_b = same_ip[2].connect(target.port)
        roundtrip(resumed_b)
        # Native entitlement suspension, never an artificial profile/core ACK.
        suspended = api.put(
            f"/v1/admin/subscriptions/{subscription_id}/suspension",
            json={
                "request_key": "owned_ip_suspend_" + uuid4().hex,
                "reason": "Owned IP lease entitlement check",
                "clock": "continue",
            },
        )
        assert suspended.status_code == 200, (
            "native_subscription_suspend_failed"
        )
        wait_closed(resumed_a)
        wait_closed(resumed_b)
        denied(same_ip[0], target.port)
        for core in cores:
            state = _data(
                api.get(f"/v1/admin/network/cores/{core['id']}/runtime"),
                "native_final_stopped_state_missing",
            )
            assert (
                state["observed_status"] == "stopped"
                and state["automation_paused"] is True
            ), "prototype_falsely_acknowledged_native_runtime"
        return {
            "paid_native_installation": True,
            "same_ip_across_three_profiles": True,
            "last_close_preserves_presence_ttl": True,
            "one_n_unrestricted_current_policy": True,
            "partition_fail_closed": True,
            "node_and_subscription_entitlement": True,
            "native_runtime_stays_stopped": True,
        }


def read_drain_barrier(api, subscription_id):
    policy = _data(
        api.get(f"/v1/admin/subscriptions/{subscription_id}/ip-limit"),
        "native_drain_policy_read_failed",
    )
    effective = policy["effective_ip_policy"]
    transition = effective["transition"]
    assert effective["core_enforcement_verified"] is False, (
        "native_drain_claimed_installed_core"
    )
    assert (
        transition is not None
        and transition["status"] == "draining"
        and transition["mode"] == "drain_leases"
        and transition["reason"] == "ip_policy_draining"
        and transition["target_policy"]["enabled"] is True
        and transition["target_policy"]["max_ips"] == 1
    ), "native_drain_transition_missing"
    retry_at = dt.datetime.fromisoformat(
        transition["retry_at"].replace("Z", "+00:00")
    )
    assert retry_at > dt.datetime.now(dt.UTC), (
        "native_drain_before_barrier_not_observable"
    )
    return retry_at


def reconnect_after_drain(client, target, retry_at):
    remaining = max(0, (retry_at - dt.datetime.now(dt.UTC)).total_seconds())
    deadline = time.monotonic() + remaining + 4
    while time.monotonic() < deadline:
        connection = None
        try:
            connection = client.connect(target)
            roundtrip(connection, b"actual-native-after-drain")
            assert dt.datetime.now(dt.UTC) >= retry_at, (
                "native_drain_admitted_before_barrier"
            )
            return connection
        except (OSError, EOFError):
            if connection is not None:
                connection.close()
            time.sleep(0.02)
    raise AssertionError("native_drain_did_not_recover")


def exercise_managed_ip_policy_drains(
    api,
    subscription_id,
    stock,
    managed,
    directory,
    stack,
    target,
):
    first = BoundStockClient(
        directory,
        stock,
        managed[0],
        sorted(managed[0].endpoints)[0],
        "127.0.0.2",
        stack,
    )
    second = BoundStockClient(
        directory,
        stock,
        managed[1],
        sorted(managed[1].endpoints)[0],
        "127.0.0.3",
        stack,
    )
    third = BoundStockClient(
        directory,
        stock,
        managed[0],
        sorted(managed[0].endpoints)[1],
        "127.0.0.4",
        stack,
    )
    configure(api, subscription_id, max_ips=2, lease_seconds=8)
    a, b = first.connect(target.port), second.connect(target.port)
    roundtrip(a)
    roundtrip(b)
    configure(
        api,
        subscription_id,
        max_ips=1,
        lease_seconds=8,
        transition_mode="drain_leases",
    )
    decreased_until = read_drain_barrier(api, subscription_id)
    denied(third, target.port)
    join_seconds = (
        max(0, (decreased_until - dt.datetime.now(dt.UTC)).total_seconds()) + 4
    )
    wait_closed(a, seconds=join_seconds)
    wait_closed(b, seconds=join_seconds)
    recovered = reconnect_after_drain(first, target.port, decreased_until)
    denied(second, target.port)
    roundtrip(recovered, b"decreased-one-ip-still-live")
    configure(
        api,
        subscription_id,
        max_ips=1,
        enabled=False,
        lease_seconds=8,
    )
    wait_block_elapsed(api, subscription_id, "127.0.0.3")
    unlimited_other = second.connect(target.port)
    roundtrip(recovered, b"unlimited-existing-ip")
    roundtrip(unlimited_other, b"unlimited-second-ip")
    configure(
        api,
        subscription_id,
        max_ips=1,
        lease_seconds=8,
        transition_mode="drain_leases",
    )
    enabled_until = read_drain_barrier(api, subscription_id)
    denied(third, target.port)
    join_seconds = (
        max(0, (enabled_until - dt.datetime.now(dt.UTC)).total_seconds()) + 4
    )
    wait_closed(recovered, seconds=join_seconds)
    wait_closed(unlimited_other, seconds=join_seconds)
    resumed = reconnect_after_drain(first, target.port, enabled_until)
    wait_block_elapsed(api, subscription_id, "127.0.0.3")
    policy = _data(
        api.get(f"/v1/admin/subscriptions/{subscription_id}/ip-limit"),
        "native_drain_final_policy_read_failed",
    )["effective_ip_policy"]
    sessions = _data(
        api.get(
            f"/v1/admin/subscriptions/{subscription_id}/ip-limit/sessions",
            params={"per_page": 16},
        ),
        "native_block_read_failed",
    )
    now = dt.datetime.now(dt.UTC)
    aliases = {"127.0.0.2": "A", "127.0.0.3": "B", "127.0.0.4": "C"}
    remaining = [
        {
            "source": aliases.get(row["source_ip"], "other"),
            "expires_in_ms": round(
                (
                    dt.datetime.fromisoformat(
                        row["expires_at"].replace("Z", "+00:00")
                    )
                    - now
                ).total_seconds()
                * 1000
            ),
        }
        for row in sessions
    ]
    transition = policy["transition"]
    print(
        json.dumps(
            {
                "safe_final_drain_point": {
                    "enabled": policy["policy"]["enabled"],
                    "max_ips": policy["policy"]["max_ips"],
                    "pending_status": transition["status"]
                    if transition
                    else None,
                    "active_count": sum(
                        row["expires_in_ms"] > 0 for row in remaining
                    ),
                    "sessions": remaining,
                }
            }
        ),
        flush=True,
    )
    roundtrip(resumed, b"first-ip-live-before-second-attempt")
    print(json.dumps({"safe_final_first_socket_live": True}), flush=True)
    denied(second, target.port)
    roundtrip(resumed, b"enabled-one-ip-still-live")
    final = _data(
        api.get(f"/v1/admin/subscriptions/{subscription_id}/ip-limit"),
        "native_drain_final_policy_read_failed",
    )
    assert final["effective_ip_policy"]["transition"] is None, (
        "native_drain_final_transition_retained"
    )
    return {
        "actual_n_to_one_drain": True,
        "actual_unlimited_to_one_drain": True,
    }


def exercise_native_managed_ip_drains(
    directory,
    runtime_binary,
    managed_binary,
    binaries,
    base_url,
    admin_headers,
    sale,
    runtime,
    raw,
    namespace,
):
    with installed_ip_presence_fixture(
        directory,
        runtime_binary,
        managed_binary,
        binaries,
        base_url,
        admin_headers,
        sale,
        runtime,
        raw,
        namespace,
    ) as fixture:
        result = exercise_managed_ip_policy_drains(
            fixture.api,
            fixture.subscription_id,
            fixture.stock,
            fixture.managed,
            directory,
            fixture.stack,
            fixture.target,
        )
        for core in fixture.cores:
            state = _data(
                fixture.api.get(
                    f"/v1/admin/network/cores/{core['id']}/runtime"
                ),
                "native_drain_stopped_state_missing",
            )
            assert (
                state["observed_status"] == "stopped"
                and state["automation_paused"] is True
            ), "native_drain_falsely_acknowledged_runtime"
        return {**result, "native_runtime_stays_stopped": True}
