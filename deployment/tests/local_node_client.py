"""Actual native client traffic through the installed node's published host port."""

import json
import socket
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from deployment.papilio_installer.docker import Compose


@contextmanager
def private_http_origin(compose: Compose) -> Iterator[str]:
    origin = f"papilio-test-origin-{uuid4().hex}"
    program = (
        "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
        "class Origin(BaseHTTPRequestHandler):\n"
        " def do_GET(self):\n"
        "  content=b'papilio-installed-client-traffic'\n"
        "  self.send_response(200)\n"
        "  self.send_header('Content-Length', str(len(content)))\n"
        "  self.end_headers()\n"
        "  self.wfile.write(content)\n"
        "HTTPServer(('0.0.0.0', 8089), Origin).serve_forever()\n"
    )
    compose.run(
        "run",
        "-d",
        "--no-deps",
        "--name",
        origin,
        "--entrypoint",
        "python",
        "api",
        "-c",
        program,
        capture=True,
    )
    try:
        yield origin
    finally:
        subprocess.run(
            ["docker", "rm", "--force", origin], check=True, capture_output=True, timeout=20
        )


def published_client_traffic(compose: Compose, directory: Path, uri: str) -> None:
    binary = directory / "installed-xray-client"
    if not binary.exists():
        with binary.open("wb") as output:
            compose.run(
                "run",
                "-T",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "cat",
                "local-node",
                "/usr/local/bin/xray",
                stdout=output,
            )
        binary.chmod(0o700)
    endpoint = urlsplit(uri)
    assert endpoint.scheme == "vless" and endpoint.username
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        proxy_port = listener.getsockname()[1]
    path = directory / "installed-client.json"
    configuration = {
        "log": {"loglevel": "none"},
        "inbounds": [{"protocol": "http", "listen": "127.0.0.1", "port": proxy_port}],
        "outbounds": [
            {
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": endpoint.hostname,
                            "port": endpoint.port,
                            "users": [{"id": endpoint.username, "encryption": "none"}],
                        }
                    ]
                },
            }
        ],
    }
    path.write_text(json.dumps(configuration))
    path.chmod(0o600)
    with (
        private_http_origin(compose) as origin,
        (directory / "installed-client.log").open("w") as log,
    ):
        process = subprocess.Popen(
            [str(binary), "run", "-config", str(path)], stdout=log, stderr=subprocess.STDOUT
        )
        try:
            deadline = time.monotonic() + 10
            while True:
                try:
                    with socket.create_connection(("127.0.0.1", proxy_port), timeout=0.1):
                        break
                except OSError:
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise AssertionError(
                            "The installed native client did not become ready."
                        ) from None
                    time.sleep(0.05)
            # Only the VPN server can resolve this private Compose service hostname.
            # Explicit proxy selection prevents localhost/no_proxy bypass.
            request = Request(f"http://{origin}:8089/")
            request.set_proxy(f"127.0.0.1:{proxy_port}", "http")
            deadline = time.monotonic() + 90
            while True:
                try:
                    with urlopen(request, timeout=5) as response:
                        assert response.status == 200
                        assert response.read() == b"papilio-installed-client-traffic"
                        break
                except (OSError, URLError) as error:
                    if time.monotonic() >= deadline:
                        raise AssertionError(
                            "The installed subscription did not recover traffic "
                            f"({type(error).__name__})."
                        ) from None
                    time.sleep(0.1)
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
