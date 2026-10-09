"""Owned TLS/VLESS wire probe; no native application authority."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import http.client
import json
import os
import select
import signal
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

CURRENT_PHASE = "setup"
PARTIAL_RESULTS: dict[str, bool] = {}
CHILD_ERROR = "none"
STARTUP_DIAGNOSTIC: dict[str, object] = {}


def encoded(value: object) -> bytes:
    return json.dumps(
        value, separators=(",", ":"), ensure_ascii=False
    ).encode()


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def private_write(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def reserve_port() -> int:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        return int(reservation.getsockname()[1])


class UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path: Path) -> None:
        super().__init__("localhost", timeout=8)
        self.path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(self.timeout)
        self.sock.connect(str(self.path))


class Upstream:
    def __init__(self, mode: str, burst_bytes: int = 512 * 1024) -> None:
        self.mode = mode
        self.burst_bytes = burst_bytes
        self.stop = threading.Event()
        self.accepted = threading.Event()
        self.lock = threading.Lock()
        self.sockets: set[socket.socket] = set()
        self.threads: list[threading.Thread] = []
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(8)
        self.listener.settimeout(0.1)
        self.port = int(self.listener.getsockname()[1])
        self.thread = threading.Thread(target=self.accept, daemon=True)
        self.thread.start()

    def accept(self) -> None:
        while not self.stop.is_set():
            try:
                connection, _ = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            connection.settimeout(5)
            with self.lock:
                self.sockets.add(connection)
                worker = threading.Thread(
                    target=self.serve, args=(connection,), daemon=True
                )
                self.threads.append(worker)
            worker.start()

    def serve(self, connection: socket.socket) -> None:
        self.accepted.set()
        try:
            if self.mode == "no_read":
                self.stop.wait(10)
            elif self.mode == "burst":
                assert connection.recv(1) == b"F"
                connection.sendall(b"D" * self.burst_bytes)
                self.stop.wait(10)
            else:
                while not self.stop.is_set():
                    payload = connection.recv(65536)
                    if not payload:
                        break
                    connection.sendall(payload)
        except (OSError, AssertionError):
            pass
        finally:
            connection.close()
            with self.lock:
                self.sockets.discard(connection)

    def close(self) -> None:
        self.stop.set()
        self.listener.close()
        with self.lock:
            connections = list(self.sockets)
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        self.thread.join(2)
        for thread in self.threads:
            thread.join(2)
        assert not self.thread.is_alive() and all(
            not thread.is_alive() for thread in self.threads
        )


class WireClient:
    def __init__(
        self,
        core: Core,
        profile: int,
        target_port: int,
        receive_bytes: int = 4096,
    ) -> None:
        raw = socket.socket()
        raw.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, receive_bytes)
        raw.settimeout(3)
        raw.connect(("127.0.0.1", core.port))
        context = ssl.create_default_context(cafile=str(core.certificate))
        self.connection = context.wrap_socket(raw, server_hostname="localhost")
        # Version, UUID, empty addons, TCP command, port then IPv4 address.
        header = (
            b"\0"
            + core.credentials[profile].bytes
            + b"\0\1"
            + target_port.to_bytes(2, "big")
            + b"\1\x7f\0\0\1"
        )
        self.connection.sendall(header)
        self.header_seen = False
        core.clients.append(self)

    def receive(self, size: int) -> bytes:
        if not self.header_seen:
            assert self.exact(2) == b"\0\0", "response_framing"
            self.header_seen = True
        return self.exact(size)

    def exact(self, size: int) -> bytes:
        payload = bytearray()
        while len(payload) < size:
            chunk = self.connection.recv(size - len(payload))
            if not chunk:
                raise EOFError("closed")
            payload.extend(chunk)
        return bytes(payload)

    def roundtrip(self, payload: bytes) -> None:
        self.connection.sendall(payload)
        assert self.receive(len(payload)) == payload, "known_payload"

    def close(self) -> None:
        self.connection.close()


class Core:
    def __init__(
        self,
        binary: Path,
        root: Path,
        settings_transform: Callable[[dict], None] | None = None,
    ) -> None:
        self.root = root
        self.port = reserve_port()
        self.clients: list[WireClient] = []
        self.process: subprocess.Popen[bytes] | None = None
        inputs = root / "inputs"
        inputs.mkdir(mode=0o700)
        self.journal = root / "journal"
        self.certificate = inputs / "cert.pem"
        key_path = inputs / "key.pem"
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]
        )
        now = dt.datetime.now(dt.timezone.utc)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=1))
            .not_valid_after(now + dt.timedelta(hours=1))
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName("localhost")]),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        private_write(
            self.certificate,
            certificate.public_bytes(serialization.Encoding.PEM),
        )
        private_write(
            key_path,
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        )
        self.credentials = {1: uuid.uuid4(), 2: uuid.uuid4()}
        bindings = [
            {
                "profile_id": number,
                "generation": 0,
                "configuration_id": 1,
                "configuration_revision": 1,
                "counter_identity": f"owned-{number}",
                "inbound_tag": "node-1",
            }
            for number in (1, 2)
        ]
        materials = [
            {"path": str(path), "sha256": digest(path.read_bytes())}
            for path in (self.certificate, key_path)
        ]
        document = {
            "log": {"loglevel": "none"},
            "inbounds": [
                {
                    "tag": "node-1",
                    "listen": "127.0.0.1",
                    "port": self.port,
                    "protocol": "vless",
                    "settings": {
                        "decryption": "none",
                        "clients": [
                            {
                                "id": str(self.credentials[number]),
                                "email": f"owned-{number}",
                                "level": 0,
                                "flow": "",
                            }
                            for number in (1, 2)
                        ],
                    },
                    "streamSettings": {
                        "network": "tcp",
                        "security": "tls",
                        "tlsSettings": {
                            "certificates": [
                                {
                                    "certificateFile": str(self.certificate),
                                    "keyFile": str(key_path),
                                }
                            ]
                        },
                    },
                }
            ],
            "outbounds": [
                {"tag": "direct", "protocol": "freedom", "settings": {}}
            ],
            "policy": {
                "levels": {
                    "0": {
                        "handshake": 3,
                        "connIdle": 20,
                        "uplinkOnly": 3,
                        "downlinkOnly": 3,
                        "bufferSize": 64,
                    }
                }
            },
        }
        policy = {
            "remote_read_buffer_bytes": 65536,
            "tcp_listener_send_buffer_bytes": 4096,
            "tcp_listener_min_effective_send_buffer_bytes": 4096,
            "tcp_listener_max_effective_send_buffer_bytes": 16384,
            "max_certificate_bytes": 65536,
            "max_executable_bytes": 256 * 1024 * 1024,
            "max_json_depth": 32,
            "max_document_bytes": 131072,
            "max_control_concurrency": 4,
            "max_outbound_connections": 8,
            "dial_timeout_ms": 3000,
            "max_profiles": 8,
            "max_sessions": 8,
            "max_operations": 64,
            "max_barriers": 8,
            "max_snapshot_bytes": 131072,
            "max_control_bytes": 65536,
            "drain_timeout_ms": 4000,
            "control_timeout_ms": 3000,
        }
        installation = {
            "materials_sha256": digest(encoded(materials)),
            "executable_sha256": digest(binary.read_bytes()),
            "document_sha256": digest(encoded(document)),
            "bindings_sha256": digest(encoded(bindings)),
        }
        settings = {
            "enabled": True,
            "accounting_mode": "legacy_component",
            "policy": policy,
            "input_root": str(inputs),
            "control_root": str(self.journal),
            "installation": installation,
            "document": document,
            "bindings": bindings,
            "certificates": materials,
            "internal_targets": [],
        }
        if settings_transform is not None:
            settings_transform(settings)
            settings["installation"]["document_sha256"] = digest(
                encoded(settings["document"])
            )
            settings["installation"]["materials_sha256"] = digest(
                encoded(settings["certificates"])
            )
        self.settings_path = root / "settings.json"
        private_write(self.settings_path, encoded(settings))
        self.command = [
            str(binary),
            "--run",
            "--config",
            str(self.settings_path),
            "--max-config-bytes",
            "262144",
            "--max-config-depth",
            "40",
        ]
        self.stderr_path = root / "startup.stderr"
        private_write(self.stderr_path, b"")
        assert os.getloadavg()[0] <= 8, "owned_core_load_preflight"
        self.process = subprocess.Popen(
            self.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        assert self.process.stderr is not None

        def drain_stderr() -> None:
            retained = 0
            with self.stderr_path.open("wb") as stream:
                while True:
                    chunk = self.process.stderr.read(4096)
                    if not chunk:
                        return
                    if retained < 8192:
                        part = chunk[: 8192 - retained]
                        stream.write(part)
                        retained += len(part)

        self.stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
        self.stderr_thread.start()
        assert self.process.stdout is not None
        try:
            ready, _, _ = select.select([self.process.stdout], [], [], 15)
            if not ready:
                raise AssertionError("child_start_timeout")
            ready_bytes = self.process.stdout.readline(8193)
            private_write(root / "startup.stdout", ready_bytes[:8192])
            response = json.loads(ready_bytes)
            global CHILD_ERROR
            code = response.get("error", "none")
            CHILD_ERROR = (
                code
                if isinstance(code, str)
                and code.startswith("managed_")
                and code.replace("_", "").isalpha()
                else "unavailable"
            )
            assert response.get("state") == "isolated_prototype_running", (
                "child_not_ready"
            )
            self.epoch = response["epoch"]
            self.closed_startup_receipt = response.get(
                "closed_startup_receipt"
            )
        except BaseException:
            self.close(crash=True)
            global STARTUP_DIAGNOSTIC
            stderr = self.stderr_path.read_bytes()
            diagnostic_root = (
                Path(__file__).resolve().parents[4]
                / "data/core-validation/managed-xray-startup"
            )
            diagnostic_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            diagnostic_root.chmod(0o700)
            diagnostic = diagnostic_root / uuid.uuid4().hex
            diagnostic.mkdir(mode=0o700)
            private_write(diagnostic / "stderr.txt", stderr)
            stdout_path = root / "startup.stdout"
            stdout = stdout_path.read_bytes() if stdout_path.is_file() else b""
            private_write(diagnostic / "stdout.txt", stdout)
            STARTUP_DIAGNOSTIC = {
                "exit_code": self.process.returncode,
                "stdout_bytes": len(stdout),
                "stderr_bytes": len(stderr),
                "panic_marker": b"panic:" in stderr,
                "stdout_empty": not stdout,
                "private_diagnostic": str(
                    diagnostic.relative_to(Path(__file__).resolve().parents[4])
                ),
            }
            raise

    def request(
        self, method: str, path: str, body: object | None = None
    ) -> tuple[int, dict]:
        connection = UnixHTTP(self.journal / "control.sock")
        try:
            connection.request(
                method,
                path,
                body=encoded(body) if body is not None else None,
                headers={"Content-Type": "application/json"}
                if body is not None
                else {},
            )
            response = connection.getresponse()
            return response.status, json.loads(response.read(131073))
        finally:
            connection.close()

    def profile(self, number: int) -> dict:
        status, result = self.request("GET", "/v1/observe")
        assert status == 200 and result["state"] == "nonfinal_live_observation"
        return next(
            profile
            for profile in result["profiles"]
            if profile["totals"]["binding"]["profile_id"] == number
        )

    def wait_operation(self, number: int, kind: str) -> None:
        deadline = time.monotonic() + 5
        consecutive = 0
        while time.monotonic() < deadline:
            count = self.profile(number)["operation_kinds"].get(kind, 0)
            consecutive = consecutive + 1 if count else 0
            if consecutive >= 3:
                return
            time.sleep(0.02)
        raise AssertionError("required_operation_not_active")

    def freeze(self, number: int, barrier: str | None = None) -> dict:
        status, result = self.request(
            "POST",
            "/v1/freeze",
            {
                "epoch": self.epoch,
                "barrier_id": barrier or uuid.uuid4().hex,
                "profile_ids": [number],
            },
        )
        assert (
            status == 200 and result["state"] == "durable_prototype_snapshot"
        ), "barrier_unresolved"
        assert (
            result["snapshot"]["profiles"][0]["binding"]["profile_id"]
            == number
        )
        assert self.profile(number)["active_operations"] == 0
        return result

    def close(self, crash: bool = False) -> None:
        for client in self.clients:
            client.close()
        if self.process is not None:
            if self.process.poll() is None:
                os.killpg(
                    self.process.pid,
                    signal.SIGKILL if crash else signal.SIGTERM,
                )
            try:
                self.process.wait(8)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(3)
            if self.process.stdout is not None:
                self.process.stdout.close()
            self.stderr_thread.join(2)
            assert not self.stderr_thread.is_alive(), (
                "owned_stderr_reader_survived"
            )
            if self.process.stderr is not None:
                self.process.stderr.close()
        with socket.socket() as check:
            check.settimeout(0.2)
            assert check.connect_ex(("127.0.0.1", self.port)) != 0, (
                "owned_listener_survived"
            )

    def refuses_restart(self) -> None:
        assert os.getloadavg()[0] <= 8, "owned_core_load_preflight"
        process = subprocess.Popen(
            self.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            stdout, _ = process.communicate(timeout=8)
            assert (
                process.returncode != 0
                and json.loads(stdout)["state"] == "unresolved"
            ), "lost_epoch_resumed"
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(3)


def exercise(binary: Path, root: Path) -> dict[str, bool]:
    global CURRENT_PHASE
    results = PARTIAL_RESULTS
    for mode in ("echo", "no_read", "burst"):
        directory = root / mode
        directory.mkdir(mode=0o700)
        echo = Upstream("echo")
        target = Upstream(mode) if mode != "echo" else echo
        core: Core | None = None
        sender: threading.Thread | None = None
        try:
            CURRENT_PHASE = mode + ".start"
            core = Core(binary, directory)
            CURRENT_PHASE = mode + ".traffic"
            b = WireClient(core, 2, echo.port)
            b.roundtrip(b"owned-B-before")
            a = WireClient(core, 1, target.port)
            if mode == "echo":
                a.roundtrip(b"owned-A-known-payload")
                barrier = uuid.uuid4().hex
                CURRENT_PHASE = "echo.freeze"
                snapshot = core.freeze(1, barrier)
                assert snapshot["snapshot"]["profiles"][0][
                    "upload_bytes"
                ] == len(b"owned-A-known-payload")
                assert snapshot["snapshot"]["profiles"][0][
                    "download_bytes"
                ] == len(b"owned-A-known-payload")
                b.roundtrip(b"owned-B-after-A-frozen")
                status, replay = core.request(
                    "POST",
                    "/v1/freeze",
                    {
                        "epoch": core.epoch,
                        "barrier_id": barrier,
                        "profile_ids": [1],
                    },
                )
                assert status == 200 and replay == snapshot, (
                    "immutable_replay_changed"
                )
                assert a.connection.recv(1) == b"", "established_A_not_closed"
                denied = WireClient(core, 1, target.port)
                try:
                    denied.roundtrip(b"must-not-pass")
                except (EOFError, OSError):
                    pass
                else:
                    raise AssertionError("new_A_admitted")
                results[
                    "persistent_known_payload_A_freeze_B_unaffected_replay"
                ] = True
            elif mode == "no_read":

                def send(
                    owned_connection: socket.socket = a.connection,
                ) -> None:
                    try:
                        for _ in range(512):
                            owned_connection.sendall(b"U" * 65536)
                    except OSError:
                        pass

                sender = threading.Thread(target=send, daemon=True)
                sender.start()
                CURRENT_PHASE = "no_read.remote_write_observation"
                core.wait_operation(1, "remote_write")
                CURRENT_PHASE = "no_read.freeze"
                core.freeze(1)
                b.roundtrip(b"owned-B-after-raw-write-freeze")
                results["actual_remote_write_joined"] = True
            else:
                a.connection.sendall(b"F")
                CURRENT_PHASE = "burst.first_flush_observation"
                core.wait_operation(1, "decoded_first_buffered_flush")
                CURRENT_PHASE = "burst.freeze"
                core.freeze(1)
                b.roundtrip(b"owned-B-after-first-flush-freeze")
                results["actual_first_buffered_flush_joined"] = True
            core.close()
            core.refuses_restart()
            results["prior_epoch_restart_refused"] = True
        finally:
            if core is not None:
                core.close(crash=True)
            if sender is not None:
                sender.join(3)
                assert not sender.is_alive(), "owned_sender_survived"
            if target is not echo:
                target.close()
            echo.close()
    directory = root / "crash"
    directory.mkdir(mode=0o700)
    core = None
    echo = Upstream("echo")
    try:
        CURRENT_PHASE = "crash.start"
        core = Core(binary, directory)
        a = WireClient(core, 1, echo.port)
        a.roundtrip(b"owned-live-before-crash")
        CURRENT_PHASE = "crash.stop"
        core.close(crash=True)
        assert (
            not list(core.journal.glob("*.intent"))
            and (core.journal / "epoch-active.json").is_file()
        )
        core.refuses_restart()
        results["crash_without_freeze_unresolved_no_resume"] = True
    finally:
        if core is not None:
            core.close(crash=True)
        echo.close()
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()

    def deadline(_signum: int, _frame: object) -> None:
        raise TimeoutError("owned_probe_deadline")

    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(90)
    try:
        with tempfile.TemporaryDirectory(
            prefix="papilio-managed-tls-"
        ) as directory:
            root = Path(directory)
            root.chmod(0o700)
            results = exercise(args.binary.resolve(), root)
        print(
            json.dumps(
                {
                    "state": "passed",
                    "scope": (
                        "actual_TLS_VLESS_independent_wire_client_"
                        "no_grant_authority"
                    ),
                    "cases": results,
                    "duration_seconds": round(time.monotonic() - started, 3),
                    "owned_cleanup": True,
                }
            )
        )
        return 0
    except Exception as error:
        print(
            json.dumps(
                {
                    "state": "failed",
                    "safe_error_type": type(error).__name__,
                    "phase": CURRENT_PHASE,
                    "child_error": CHILD_ERROR,
                    "completed_cases": PARTIAL_RESULTS,
                    "duration_seconds": round(time.monotonic() - started, 3),
                    "not_final_accounting_authority": True,
                }
            )
        )
        return 1
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    raise SystemExit(main())
