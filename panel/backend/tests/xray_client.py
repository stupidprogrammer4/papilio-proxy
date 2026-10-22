"""An actual Xray client consuming the generated VLESS URI, with a local HTTP origin."""

import json
import subprocess
import threading
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from conftest import until
from test_node_runtime import listening, port, stop


class TestOrigin(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        payload = b"papilio-actual-subscription-client"
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        pass


@dataclass(frozen=True)
class HttpTunnelProbe:
    proxy_port: int
    origin_port: int

    def fetch(self) -> bytes:
        request = urllib.request.Request(f"http://127.0.0.1:{self.origin_port}/")
        request.set_proxy(f"127.0.0.1:{self.proxy_port}", "http")
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.read()


@contextmanager
def subscription_client(binary: str, directory: Path, uri: str) -> Iterator[HttpTunnelProbe]:
    endpoint, proxy_port = urlsplit(uri), port()
    assert endpoint.scheme == "vless" and endpoint.username is not None
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
    path = directory / "subscription-client.json"
    path.write_text(json.dumps(configuration))
    path.chmod(0o600)
    origin = ThreadingHTTPServer(("127.0.0.1", 0), TestOrigin)
    thread = threading.Thread(target=origin.serve_forever, daemon=True)
    thread.start()
    with (directory / "subscription-client.log").open("w") as log:
        process = subprocess.Popen(
            [binary, "run", "-config", str(path)], stdout=log, stderr=subprocess.STDOUT
        )
        try:
            until(lambda: listening(proxy_port), timeout=10)
            yield HttpTunnelProbe(proxy_port, origin.server_port)
        finally:
            stop(process)
            origin.shutdown()
            origin.server_close()
            thread.join(timeout=3)
