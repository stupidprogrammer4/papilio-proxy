"""Drop the first committed epoch-rollover response in a local API relay."""

import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

MAX_RELAY_BYTES = 2_097_152


class ManagedRolloverResponseDrop:
    def __init__(
        self, api_url: str, *, hold_first_rollover_response: bool = False
    ) -> None:
        self.api_url = api_url
        self._hold_first_rollover_response = hold_first_rollover_response
        self._lock = threading.Lock()
        self._dropped = False
        self._first_rollover_committed = threading.Event()
        self._release_first_rollover = threading.Event()
        self._rollover_responses: list[tuple[str, int, str]] = []
        self._events: list[tuple[str, str, int]] = []
        self._client = httpx.Client(
            timeout=5,
            trust_env=False,
            follow_redirects=False,
            headers={"Accept-Encoding": "identity"},
        )
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

            def do_GET(self) -> None:
                self.forward()

            def do_POST(self) -> None:
                self.forward()

            def forward(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > MAX_RELAY_BYTES:
                    self.send_error(413)
                    return
                body = self.rfile.read(length)
                headers = {
                    name: self.headers[name]
                    for name in ("Content-Type", "X-Papilio-Node-Key")
                    if self.headers.get(name) is not None
                }
                try:
                    with owner._client.stream(
                        self.command,
                        owner.api_url + self.path,
                        content=body if self.command == "POST" else None,
                        headers=headers,
                    ) as upstream:
                        response_body = bytearray()
                        for chunk in upstream.iter_bytes():
                            if (
                                len(response_body) + len(chunk)
                                > MAX_RELAY_BYTES
                            ):
                                self.send_error(502)
                                return
                            response_body.extend(chunk)
                        status_code = upstream.status_code
                except httpx.HTTPError:
                    with owner._lock:
                        owner._events.append(
                            (self.command, "upstream_error", 502)
                        )
                    self.send_error(502)
                    return
                endpoint = self.path.split("?", 1)[0].rsplit("/", 1)[-1]
                if endpoint not in {
                    "claim",
                    "acknowledge",
                    "windows",
                    "admission",
                    "finalize",
                    "successor",
                    "seal",
                    "rollover",
                }:
                    endpoint = "other"
                with owner._lock:
                    owner._events.append((self.command, endpoint, status_code))
                is_rollover = (
                    self.command == "POST"
                    and "/managed-epochs/" in self.path
                    and self.path.endswith("/rollover")
                )
                drop_response = False
                if is_rollover:
                    request_digest = hashlib.sha256(body).hexdigest()
                    response_digest = hashlib.sha256(response_body).hexdigest()
                    with owner._lock:
                        owner._rollover_responses.append(
                            (
                                request_digest,
                                status_code,
                                response_digest,
                            )
                        )
                        drop_response = not owner._dropped
                        owner._dropped = True
                    if drop_response and owner._hold_first_rollover_response:
                        owner._first_rollover_committed.set()
                        owner._release_first_rollover.wait(timeout=30)
                if drop_response:
                    self.close_connection = True
                    return
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="managed-rollover-fault-relay",
            daemon=True,
        )

    @property
    def url(self) -> str:
        host = str(self._server.server_address[0])
        port = self._server.server_port
        return f"http://{host}:{port}"

    def __enter__(self) -> "ManagedRolloverResponseDrop":
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._release_first_rollover.set()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
        self._client.close()

    def rollover_responses(self) -> tuple[tuple[str, int, str], ...]:
        with self._lock:
            return tuple(self._rollover_responses)

    def wait_for_held_rollover(self, timeout: float) -> bool:
        return self._first_rollover_committed.wait(timeout)

    def release_held_rollover(self) -> None:
        self._release_first_rollover.set()

    def events(self) -> tuple[tuple[str, str, int], ...]:
        with self._lock:
            return tuple(self._events)
