"""Wait for the served panel/API and a verified HTTPS certificate."""

import argparse
import http.client
import math
import socket
import ssl
import time
from urllib.parse import urlsplit


def check(origin: str, timeout: float) -> None:
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or not origin.isascii()
        or any(char.isspace() for char in origin)
    ):
        raise ValueError("Expected a public HTTP(S) origin")
    port = 8443 if parsed.scheme == "https" else 8080
    for path, media_type in (
        ("/", "text/html"),
        ("/healthz", "application/json"),
    ):
        connection = http.client.HTTPConnection("web", port, timeout=timeout)
        try:
            if parsed.scheme == "https":
                transport = socket.create_connection(("web", port), timeout)
                try:
                    connection.sock = ssl.create_default_context().wrap_socket(
                        transport, server_hostname=parsed.hostname
                    )
                except BaseException:
                    transport.close()
                    raise
            connection.request("GET", path, headers={"Host": parsed.netloc})
            response = connection.getresponse()
            if response.status != 200 or media_type not in (
                response.getheader("Content-Type") or ""
            ):
                raise OSError("Panel or API response is not ready")
        finally:
            connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin")
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--attempt-timeout", type=float, default=3)
    parser.add_argument("--retry-seconds", type=float, default=1)
    args = parser.parse_args()
    capacities = (args.timeout, args.attempt_timeout, args.retry_seconds)
    if not all(math.isfinite(value) and value > 0 for value in capacities):
        parser.error("Readiness capacities must be positive")
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        try:
            check(
                args.origin,
                min(args.attempt_timeout, deadline - time.monotonic()),
            )
            print("Gateway panel/API and transport verified.")
            return
        except (OSError, http.client.HTTPException):
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(args.retry_seconds, remaining))
    raise SystemExit(
        "Gateway not ready; inspect panel, API, DNS and TLS state."
    )


if __name__ == "__main__":
    main()
