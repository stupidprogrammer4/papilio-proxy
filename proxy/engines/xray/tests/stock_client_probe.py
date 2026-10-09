"""Owned exact-reference stock TLS/Reality client + private response-loss probe.

No native application or grant authority. Keys remain only in temporary files.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import signal
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from typing import Any
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import x25519

import barrier_probe
from barrier_probe import Core, Upstream, digest, encoded, private_write, reserve_port


def exact(connection: socket.socket, size: int) -> bytes:
    result = bytearray()
    while len(result) < size:
        chunk = connection.recv(size - len(result))
        if not chunk:
            raise EOFError("owned_connection_closed")
        result.extend(chunk)
    return bytes(result)


class Fallback:
    """Owned bounded TLS1.3 target, handshake in each worker, tracked cleanup."""

    def __init__(self, settings: dict[str, Any]) -> None:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.set_alpn_protocols(["h2", "http/1.1"])
        paths = settings["certificates"]
        context.load_cert_chain(paths[0]["path"], paths[1]["path"])
        self.context = context
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(8)
        self.listener.settimeout(0.1)
        self.port = self.listener.getsockname()[1]
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.connections: set[socket.socket] = set()
        self.workers: list[threading.Thread] = []
        self.capacity = threading.BoundedSemaphore(8)
        self.thread = threading.Thread(target=self.accept, daemon=True)
        self.thread.start()

    def accept(self) -> None:
        while not self.stop.is_set():
            try:
                raw, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            if not self.capacity.acquire(blocking=False):
                raw.close()
                continue
            raw.settimeout(3)
            try:
                connection = self.context.wrap_socket(raw, server_side=True, do_handshake_on_connect=False)
            except OSError:
                raw.close()
                self.capacity.release()
                continue
            with self.lock:
                self.connections.add(connection)
                worker = threading.Thread(target=self.serve, args=(connection,), daemon=True)
                self.workers.append(worker)
            worker.start()

    def serve(self, connection: ssl.SSLSocket) -> None:
        try:
            connection.do_handshake()
            connection.recv(4096)
        except OSError:
            pass
        finally:
            connection.close()
            with self.lock:
                self.connections.discard(connection)
            self.capacity.release()

    def close(self) -> None:
        self.stop.set()
        self.listener.close()
        with self.lock:
            connections = list(self.connections)
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        self.thread.join(2)
        for worker in self.workers:
            worker.join(4)
        assert not self.thread.is_alive() and all(not worker.is_alive() for worker in self.workers), "fallback_cleanup"


class StockClient:
    def __init__(self, binary: Path, core: Core, profile: int, mode: str, public_key: str | None, short_id: str | None) -> None:
        self.port = reserve_port()
        self.connections: list[socket.socket] = []
        transport: dict[str, Any] = {"network": "tcp", "security": mode}
        if mode == "tls":
            transport["tlsSettings"] = {"serverName": "localhost", "allowInsecure": False, "certificates": [{"certificateFile": str(core.certificate), "usage": "verify"}]}
        else:
            transport["realitySettings"] = {"serverName": "localhost", "fingerprint": "chrome", "password": public_key, "shortId": short_id}
        document = {"log": {"loglevel": "none"}, "inbounds": [{"listen": "127.0.0.1", "port": self.port, "protocol": "socks", "settings": {"auth": "noauth", "udp": False}}], "outbounds": [{"protocol": "vless", "settings": {"vnext": [{"address": "127.0.0.1", "port": core.port, "users": [{"id": str(core.credentials[profile]), "encryption": "none", "flow": ""}]}]}, "streamSettings": transport}]}
        path = core.root / f"stock-client-{profile}.json"
        private_write(path, encoded(document))
        assert os.getloadavg()[0] <= 8, "owned_core_load_preflight"
        self.process = subprocess.Popen([str(binary), "run", "-config", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                assert self.process.poll() is None, "stock_child_exit"
                try:
                    with socket.create_connection(("127.0.0.1", self.port), timeout=0.1):
                        return
                except OSError:
                    time.sleep(0.02)
            raise TimeoutError("stock_listener_start")
        except BaseException:
            self.close()
            raise

    def connect(self, target: int) -> socket.socket:
        connection = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        self.connections.append(connection)
        connection.sendall(b"\x05\x01\x00")
        assert exact(connection, 2) == b"\x05\x00", "stock_socks_negotiation"
        connection.sendall(b"\x05\x01\x00\x01\x7f\x00\x00\x01" + target.to_bytes(2, "big"))
        reply = exact(connection, 4)
        assert reply[:2] == b"\x05\x00", "stock_socks_destination"
        size = {1: 4, 4: 16}.get(reply[3])
        if size is None:
            assert reply[3] == 3, "stock_socks_address"
            size = exact(connection, 1)[0]
        exact(connection, size + 2)
        return connection

    def close(self) -> None:
        for connection in self.connections:
            connection.close()
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
        try:
            self.process.wait(5)
        except subprocess.TimeoutExpired:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait(3)
        with socket.socket() as check:
            check.settimeout(0.1)
            assert check.connect_ex(("127.0.0.1", self.port)) != 0, "stock_listener_survived"


def roundtrip(connection: socket.socket, payload: bytes) -> None:
    connection.sendall(payload)
    assert exact(connection, len(payload)) == payload, "stock_known_payload"


def drop_response(core: Core, barrier: str) -> dict[str, Any]:
    payload = encoded({"epoch": core.epoch, "barrier_id": barrier, "profile_ids": [1]})
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(3)
        connection.connect(str(core.journal / "control.sock"))
        header = b"POST /v1/freeze HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: " + str(len(payload)).encode() + b"\r\nConnection: close\r\n\r\n"
        connection.sendall(header + payload)
        # Deliberately do not read any response or final receipt.
    deadline = time.monotonic() + 5
    intent = core.journal / f"{barrier}.intent"
    snapshot = core.journal / f"{barrier}.json"
    while time.monotonic() < deadline:
        if intent.is_file() and snapshot.is_file():
            break
        time.sleep(0.02)
    assert intent.is_file() and snapshot.is_file(), "lost_response_not_durable"
    persisted = json.loads(snapshot.read_bytes())
    status, replay = core.request("POST", "/v1/freeze", {"epoch": core.epoch, "barrier_id": barrier, "profile_ids": [1]})
    assert status == 200 and replay["state"] == "durable_prototype_snapshot", "lost_response_replay"
    assert replay["snapshot"] == persisted, "lost_response_snapshot_changed"
    assert replay["receipt"]["snapshot_sha256"] == digest(snapshot.read_bytes()), "lost_response_receipt_changed"
    status, repeated = core.request("POST", "/v1/freeze", {"epoch": core.epoch, "barrier_id": barrier, "profile_ids": [1]})
    assert status == 200 and repeated == replay, "lost_response_second_replay_changed"
    return replay


def stage_stock(source: Path, references: Path, root: Path) -> Path:
    assert references.stat().st_size <= 1048576, "stock_reference_capacity"
    records = json.loads(references.read_bytes())
    reference = next(record for record in records if record["name"] == "xray")
    assert reference["version"] == "26.3.27", "stock_reference_version"
    assert source.stat().st_size <= 256 * 1024 * 1024, "stock_binary_capacity"
    content = source.read_bytes()
    assert digest(content) == reference["binary_sha256"], "stock_reference_digest"
    staged = root / "stock-xray"
    private_write(staged, content)
    staged.chmod(0o700)
    assert os.getloadavg()[0] <= 8, "owned_core_load_preflight"
    version = subprocess.run([str(staged), "version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, check=True)
    assert len(version.stdout) <= 8192 and version.stdout.startswith(b"Xray 26.3.27 "), "stock_observed_version"
    assert digest(staged.read_bytes()) == reference["binary_sha256"], "stock_staged_changed"
    return staged


class SecurityFixture:
    """Same owned TLS/Reality configuration used by both physical probes."""

    def __init__(self, mode: str) -> None:
        assert mode in {"tls", "reality"}
        self.mode = mode
        self.fallback: Fallback | None = None
        self.public_key: str | None = None
        self.short_id: str | None = None

    def configure(self, settings: dict[str, Any]) -> None:
        if self.mode == "tls":
            return
        self.fallback = Fallback(settings)
        key = x25519.X25519PrivateKey.generate()
        raw_private = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        raw_public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        encode_key = lambda payload: base64.urlsafe_b64encode(payload).decode().rstrip("=")
        self.public_key = encode_key(raw_public)
        self.short_id = os.urandom(8).hex()
        target = f"127.0.0.1:{self.fallback.port}"
        settings["document"]["inbounds"][0]["streamSettings"] = {"network": "tcp", "security": "reality", "realitySettings": {"show": False, "dest": target, "xver": 0, "serverNames": ["localhost"], "privateKey": encode_key(raw_private), "shortIds": [self.short_id]}}
        settings["internal_targets"] = [{"requested": target, "address": "127.0.0.1", "port": self.fallback.port}]

    def close(self) -> None:
        if self.fallback is not None:
            self.fallback.close()


def exercise(binary: Path, stock: Path, root: Path, mode: str) -> None:
    security = SecurityFixture(mode)
    core: Core | None = None
    clients: list[StockClient] = []
    upstream = Upstream("echo")
    try:
        core = Core(binary, root, security.configure)
        for number in (1, 2):
            clients.append(StockClient(stock, core, number, mode, security.public_key, security.short_id))
        a, b = (client.connect(upstream.port) for client in clients)
        payload_a, payload_b = b"stock-owned-A-known", b"stock-owned-B-known"
        roundtrip(a, payload_a)
        roundtrip(b, payload_b)
        snapshot = drop_response(core, uuid.uuid4().hex)
        totals = snapshot["snapshot"]["profiles"][0]
        assert totals["upload_bytes"] == len(payload_a) and totals["download_bytes"] == len(payload_a), "stock_snapshot_totals"
        assert core.profile(1)["active_operations"] == 0, "stock_admitted_operations_remain"
        denied = False
        try:
            roundtrip(a, b"must-not-deliver")
        except (OSError, EOFError):
            denied = True
        assert denied, "stock_existing_A_survived"
        denied = False
        try:
            late = clients[0].connect(upstream.port)
            roundtrip(late, b"must-not-deliver")
        except (OSError, EOFError):
            denied = True
        assert denied, "stock_new_A_survived"
        roundtrip(b, b"stock-B-unaffected-after-freeze")
    finally:
        for client in clients:
            client.close()
        if core is not None:
            core.close()
        upstream.close()
        security.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--stock-binary", type=Path, required=True)
    parser.add_argument("--stock-references", type=Path, required=True)
    parser.add_argument("--mode", choices=("tls", "reality", "all"), default="all")
    args = parser.parse_args()
    started = time.monotonic()
    cases: dict[str, bool] = {}
    phase = "reference"
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("owned_matrix_deadline")))
    signal.alarm(100)
    try:
        with tempfile.TemporaryDirectory(prefix="papilio-managed-stock-") as directory:
            root = Path(directory)
            root.chmod(0o700)
            stock = stage_stock(args.stock_binary, args.stock_references, root)
            modes = ("tls", "reality") if args.mode == "all" else (args.mode,)
            for mode in modes:
                phase = mode
                case_root = root / mode
                case_root.mkdir(mode=0o700)
                exercise(args.binary, stock, case_root, mode)
                cases[f"actual_stock_{mode}_A_freeze_B_unaffected_lost_response_replay"] = True
        print(json.dumps({"state": "passed", "scope": "isolated_stock_client_component_no_grant_authority", "cases": cases, "duration_seconds": round(time.monotonic()-started,3), "owned_cleanup": True}))
        return 0
    except Exception as error:
        print(json.dumps({"state": "failed", "phase": phase, "safe_error_type": type(error).__name__, "cases": cases, "duration_seconds": round(time.monotonic()-started,3), "not_final_accounting_authority": True, "startup_diagnostic": barrier_probe.STARTUP_DIAGNOSTIC}))
        return 1
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    raise SystemExit(main())
