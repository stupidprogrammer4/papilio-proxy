"""Opt-in loopback acceptance using real, caller-selected core binaries."""

import base64
import json
import os
import socket
import ssl
import subprocess
import threading
import time
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


class TrafficTarget(BaseHTTPRequestHandler):
    payload = b"papilio-real-core-traffic-verified\n"

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, format: str, *args: object):
        pass


class OwnedTlsTarget(ThreadingHTTPServer):
    """Bound accepted sockets; perform TLS handshakes in owned workers."""

    daemon_threads = False

    def __init__(self, address, context, timeout, capacity):
        self.tls_context = context
        self.handshake_timeout = timeout
        self.connection_capacity = capacity
        self.accepted = {}
        self.accepted_lock = threading.Lock()
        self.closing = False
        super().__init__(address, TrafficTarget)

    def get_request(self):
        request, address = super().get_request()
        with self.accepted_lock:
            if self.closing or len(self.accepted) >= self.connection_capacity:
                request.close()
                raise OSError("Owned TLS fixture connection capacity")
            self.accepted[id(request)] = request
        return request, address

    def process_request_thread(self, request, client_address):
        key = id(request)
        secured = None
        try:
            with self.accepted_lock:
                if self.closing:
                    return
                secured = self.tls_context.wrap_socket(
                    request,
                    server_side=True,
                    do_handshake_on_connect=False,
                )
                self.accepted[key] = secured
            secured.settimeout(self.handshake_timeout)
            secured.do_handshake()
            self.finish_request(secured, client_address)
        except (OSError, ssl.SSLError):
            pass
        finally:
            with self.accepted_lock:
                current = self.accepted.pop(key, None)
            if current is not None:
                self.shutdown_request(current)

    def server_close(self):
        with self.accepted_lock:
            self.closing = True
            for request in self.accepted.values():
                try:
                    request.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                request.close()
        super().server_close()
        assert not self.accepted, "Owned TLS workers survived cleanup"


class RealCoreRuntime:
    def __init__(
        self,
        root: Path,
        binaries: Path,
        timeout: float,
        *,
        tls_connection_capacity: int = 32,
    ):
        assert timeout > 0 and tls_connection_capacity > 0
        self.root = root
        self.binaries = binaries
        self.timeout = timeout
        self.tls_connection_capacity = tls_connection_capacity
        self.resources = ExitStack()
        self.processes = []

    def __enter__(self):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.resources.__enter__()
        try:
            self.prepare_targets()
        except BaseException:
            self.resources.close()
            raise
        return self

    def prepare_targets(self):
        target = ThreadingHTTPServer(("127.0.0.1", 0), TrafficTarget)
        self.resources.callback(target.server_close)
        threading.Thread(target=target.serve_forever, daemon=True).start()
        self.resources.callback(target.shutdown)
        self.target_port = target.server_port
        certificate = self.root / "localhost.crt"
        key = self.root / "localhost.key"
        assert os.getloadavg()[0] <= 8, "owned_core_load_preflight"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "ec",
                "-pkeyopt",
                "ec_paramgen_curve:P-256",
                "-nodes",
                "-keyout",
                str(key),
                "-out",
                str(certificate),
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost",
            ],
            check=True,
            capture_output=True,
            timeout=self.timeout,
        )
        key.chmod(0o600)
        self.certificate, self.key = certificate, key
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.load_cert_chain(certificate, key)
        context.set_alpn_protocols(["h2", "http/1.1"])
        tls_target = OwnedTlsTarget(
            ("127.0.0.1", 0),
            context,
            self.timeout,
            self.tls_connection_capacity,
        )
        self.resources.callback(tls_target.server_close)
        threading.Thread(target=tls_target.serve_forever, daemon=True).start()
        self.resources.callback(tls_target.shutdown)
        self.handshake_port = tls_target.server_port

    def __exit__(self, *args):
        self.resources.__exit__(*args)
        assert all(process.poll() is not None for process in self.processes)

    @staticmethod
    def port():
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            return listener.getsockname()[1]

    def file(self, name, content):
        path = self.root / name
        path.write_text(content)
        path.chmod(0o600)
        return path

    @staticmethod
    def stop(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def start(self, name, args):
        log = self.resources.enter_context(
            (self.root / f"{name}.log").open("wb")
        )
        assert os.getloadavg()[0] <= 8, "owned_core_load_preflight"
        process = subprocess.Popen(args, stdout=log, stderr=log)
        self.processes.append(process)
        self.resources.callback(self.stop, process)
        return process

    def client(self, uri):
        parsed = urlsplit(uri)
        query = {
            key: values[0] for key, values in parse_qs(parsed.query).items()
        }
        if parsed.scheme == "vmess":
            record = json.loads(base64.b64decode(uri.removeprefix("vmess://")))
            outbound = {
                "type": "vmess",
                "server": record["add"],
                "server_port": int(record["port"]),
                "uuid": record["id"],
                "security": "auto",
                "alter_id": 0,
            }
            query = {
                "type": record["net"],
                "sni": record["sni"],
                "path": record["path"],
                "serviceName": record["path"],
            }
        else:
            outbound = {
                "type": "hysteria2"
                if parsed.scheme == "hysteria2"
                else parsed.scheme,
                "server": parsed.hostname,
                "server_port": parsed.port,
            }
            identity = unquote(parsed.netloc.rsplit("@", 1)[0])
            if parsed.scheme == "ss":
                plain = base64.urlsafe_b64decode(
                    identity + "=" * (-len(identity) % 4)
                ).decode()
                method, password = plain.split(":", 1)
                outbound.update(
                    type="shadowsocks", method=method, password=password
                )
                return outbound
            if parsed.scheme in ("trojan", "hysteria2"):
                outbound["password"] = identity
            else:
                outbound["uuid"] = identity
        tls = {"enabled": True, "server_name": query["sni"]}
        if query.get("security") == "reality":
            tls.update(
                utls={"enabled": True, "fingerprint": query["fp"]},
                reality={
                    "enabled": True,
                    "public_key": query["pbk"],
                    "short_id": query["sid"],
                },
            )
            outbound["flow"] = query["flow"]
        else:
            tls["certificate_path"] = str(self.certificate)
        outbound["tls"] = tls
        if query.get("type") == "ws":
            outbound["transport"] = {"type": "ws", "path": query["path"]}
        elif query.get("type") == "grpc":
            outbound["transport"] = {
                "type": "grpc",
                "service_name": query["serviceName"],
            }
        return outbound

    def traffic(self, name, core, server, uri):
        server_file = self.file(f"{name}-server.json", server)
        binary = str(self.binaries / core)
        if core == "xray":
            check = [binary, "run", "-test", "-config", str(server_file)]
            start = [binary, "run", "-config", str(server_file)]
        elif core == "sing-box":
            check = [binary, "check", "-c", str(server_file)]
            start = [binary, "run", "-c", str(server_file)]
        else:
            check = None
            start = [binary, "server", "-c", str(server_file)]
        if check:
            assert os.getloadavg()[0] <= 8, "owned_core_load_preflight"
            result = subprocess.run(
                check, capture_output=True, timeout=self.timeout
            )
            self.file(
                f"{name}-validation.log",
                (result.stdout + result.stderr).decode(),
            )
            if result.returncode:
                raise AssertionError(
                    f"{name}: configuration rejected; inspect validation log"
                )
        server_process = self.start(name + "-server", start)
        try:
            self.exercise(name, self.client(uri), accepted=True)
            outbound = self.client(uri)
            if "uuid" in outbound:
                outbound["uuid"] = "00000000-0000-4000-8000-000000000000"
            elif outbound["type"] == "shadowsocks":
                master, _ = outbound["password"].split(":", 1)
                wrong_key = base64.b64encode(bytes(32)).decode()
                outbound["password"] = f"{master}:{wrong_key}"
            else:
                outbound["password"] = "invalid-test-credential"
            self.exercise(name + "-denied", outbound, accepted=False)
        finally:
            self.stop(server_process)

    def exercise(self, name, outbound, accepted):
        socks_port = self.port()
        config = {
            "inbounds": [
                {
                    "type": "socks",
                    "listen": "127.0.0.1",
                    "listen_port": socks_port,
                }
            ],
            "outbounds": [{**outbound, "tag": "proxy"}],
            "route": {"final": "proxy"},
        }
        client_file = self.file(f"{name}-client.json", json.dumps(config))
        client_process = self.start(
            name + "-client",
            [str(self.binaries / "sing-box"), "run", "-c", str(client_file)],
        )
        try:
            deadline = time.monotonic() + self.timeout
            result = None
            while time.monotonic() < deadline:
                assert os.getloadavg()[0] <= 8, "owned_core_load_preflight"
                result = subprocess.run(
                    [
                        "curl",
                        "--silent",
                        "--show-error",
                        "--noproxy",
                        "",
                        "--max-time",
                        "2",
                        "--proxy",
                        f"socks5h://127.0.0.1:{socks_port}",
                        f"http://127.0.0.1:{self.target_port}/proof",
                    ],
                    capture_output=True,
                    timeout=3,
                )
                if result.returncode == 0:
                    break
                if client_process.poll() is not None:
                    raise AssertionError(
                        f"{name}: client stopped; inspect private client log"
                    )
                if (
                    not accepted
                    and time.monotonic() > deadline - self.timeout + 3
                ):
                    break
                time.sleep(0.1)
            if accepted:
                assert result is not None and result.returncode == 0, (
                    f"{name}: no traffic; inspect private core logs"
                )
                assert result.stdout == TrafficTarget.payload, (
                    f"{name}: incorrect response"
                )
            else:
                assert result is not None and result.returncode != 0, (
                    f"{name}: accepted invalid credential"
                )
        finally:
            self.stop(client_process)
