"""Actual HTTP transfers verify the selected native artifact and clean failed downloads."""

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from deployment.papilio_installer.node.artifacts import download_bundle, native_platform


@dataclass
class ReleaseServer:
    body: bytes = b"controlled external node archive"
    mismatch: bool = False
    requests: int = 0
    address: str = ""


@pytest.fixture
def release_server() -> Iterator[ReleaseServer]:
    fixture = ReleaseServer()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.endswith("/SHA256SUMS"):
                digest = "0" * 64 if fixture.mismatch else hashlib.sha256(fixture.body).hexdigest()
                name = f"papilio-node-0.1.0-alpha.4-{native_platform().replace('/', '-')}.tar.gz"
                body = f"{digest}  {name}\n".encode()
            else:
                fixture.requests += 1
                body = fixture.body
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fixture.address = f"http://127.0.0.1:{server.server_port}"
    try:
        yield fixture
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_native_download_reuses_verified_cache(
    tmp_path: Path, release_server: ReleaseServer
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "VERSION").write_text("0.1.0-alpha.4\n")
    cache = tmp_path / "cache"
    result = download_bundle(source, cache, 1048576, base_url=release_server.address)
    assert result.read_bytes() == release_server.body
    assert download_bundle(source, cache, 1048576, base_url=release_server.address) == result
    assert release_server.requests == 1


@pytest.mark.parametrize("fault", ["checksum", "size"])
def test_failed_native_download_keeps_no_partial_artifact(
    tmp_path: Path, release_server: ReleaseServer, fault: str
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "VERSION").write_text("0.1.0-alpha.4\n")
    cache = tmp_path / "cache"
    release_server.mismatch = fault == "checksum"
    with pytest.raises(ValueError):
        download_bundle(
            source, cache, 1 if fault == "size" else 1048576, base_url=release_server.address
        )
    assert not list(cache.iterdir())
