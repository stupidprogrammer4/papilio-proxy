"""Release-owned image identities and archive paths must be validated before I/O."""

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass, replace
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import pytest
from deployment.papilio_installer.images import download_image_bundle, read_image_bundle

VERSION = "0.1.0-alpha.2"
ROLES = ("backend", "frontend", "postgres", "redis", "rabbitmq")


def release_source(tmp_path: Path) -> tuple[Path, dict]:
    source = tmp_path / "source"
    (source / "deployment").mkdir(parents=True)
    (source / "VERSION").write_text(VERSION + "\n")
    bundles = {}
    for arch in ("amd64", "arm64"):
        bundles[f"linux/{arch}"] = {
            "asset": f"papilio-{VERSION}-images-linux-{arch}.tar.gz",
            "sha256": "a" * 64,
            "size": 1024,
            "images": [
                {
                    "role": role,
                    "reference": f"papilio/{role}:{VERSION}-{arch}",
                    "id": "sha256:" + str(index) * 64,
                }
                for index, role in enumerate(ROLES, 1)
            ],
        }
    manifest = {"format": 1, "version": VERSION, "platforms": bundles}
    (source / "deployment/images.json").write_text(json.dumps(manifest))
    return source, manifest


@pytest.mark.parametrize("platform", ["linux/amd64", "linux/arm64"])
def test_bundle_selects_explicit_platform_and_release_owned_references(
    tmp_path: Path, platform: str
) -> None:
    source, _ = release_source(tmp_path)
    bundle = read_image_bundle(source, platform)
    assert bundle is not None
    assert bundle.version == VERSION and bundle.platform == platform
    assert bundle.size == 1024 and bundle.sha256 == "a" * 64
    assert {image.role.value for image in bundle.images} == set(ROLES)
    assert all(image.reference.startswith("papilio/") for image in bundle.images)


def test_checkout_without_manifest_keeps_source_build_path(tmp_path: Path) -> None:
    assert read_image_bundle(tmp_path, "linux/amd64") is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("asset", "../../escape.tar.gz"),
        ("asset", "https://other.invalid/images.tar.gz"),
        ("sha256", "bad"),
        ("size", 0),
        ("size", True),
        ("size", 1.5),
    ],
)
def test_invalid_bundle_metadata_is_rejected(tmp_path: Path, field: str, value: object) -> None:
    source, manifest = release_source(tmp_path)
    manifest["platforms"]["linux/amd64"][field] = value
    (source / "deployment/images.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        read_image_bundle(source, "linux/amd64")


@pytest.mark.parametrize(
    "case", ["version", "format", "missing", "duplicate", "foreign", "image_id"]
)
def test_inconsistent_manifest_never_becomes_a_build_fallback(tmp_path: Path, case: str) -> None:
    source, manifest = release_source(tmp_path)
    images = manifest["platforms"]["linux/amd64"]["images"]
    if case == "version":
        manifest["version"] = "0.1.0-alpha.3"
    elif case == "format":
        manifest["format"] = True
    elif case == "missing":
        images.pop()
    elif case == "duplicate":
        images.append(images[0].copy())
    elif case == "foreign":
        images[0]["reference"] = "unrelated/backend:latest"
    else:
        images[0]["id"] = "sha256:bad"
    (source / "deployment/images.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        read_image_bundle(source, "linux/amd64")


def test_unsupported_platform_is_an_explicit_error(tmp_path: Path) -> None:
    source, _ = release_source(tmp_path)
    with pytest.raises(ValueError, match="platform"):
        read_image_bundle(source, "linux/ppc64le")


@dataclass
class ArchiveServer:
    body: bytes = b"controlled-external-image-archive"
    requests: int = 0
    address: str = ""
    declared_extra: int = 0


@pytest.fixture
def archive_server() -> Iterator[ArchiveServer]:
    fixture = ArchiveServer()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            fixture.requests += 1
            self.send_response(200)
            self.send_header("Content-Length", str(len(fixture.body) + fixture.declared_extra))
            self.end_headers()
            self.wfile.write(fixture.body)
            self.close_connection = True

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    fixture.address = f"http://127.0.0.1:{server.server_port}"
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield fixture
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_actual_download_verifies_size_and_digest_before_cache_replay(
    tmp_path: Path, archive_server: ArchiveServer
) -> None:
    source, _ = release_source(tmp_path)
    bundle = read_image_bundle(source, "linux/amd64")
    assert bundle is not None
    bundle = replace(
        bundle,
        size=len(archive_server.body),
        sha256=hashlib.sha256(archive_server.body).hexdigest(),
    )
    cache = tmp_path / "cache"
    path = download_image_bundle(bundle, cache, base_url=archive_server.address)
    assert path.read_bytes() == archive_server.body
    assert archive_server.requests == 1
    assert download_image_bundle(bundle, cache, base_url=archive_server.address) == path
    assert archive_server.requests == 1


@pytest.mark.parametrize("fault", ["checksum", "truncated", "oversized"])
def test_invalid_transfer_preserves_cache_and_removes_only_its_temporary_file(
    tmp_path: Path, archive_server: ArchiveServer, fault: str
) -> None:
    source, _ = release_source(tmp_path)
    bundle = read_image_bundle(source, "linux/amd64")
    assert bundle is not None
    bundle = replace(
        bundle,
        size=len(archive_server.body),
        sha256=hashlib.sha256(archive_server.body).hexdigest(),
    )
    if fault == "checksum":
        archive_server.body = b"x" * len(archive_server.body)
    elif fault == "truncated":
        archive_server.declared_extra = 10
        bundle = replace(bundle, size=len(archive_server.body) + 10)
    else:
        bundle = replace(bundle, size=len(archive_server.body) - 1)
    cache = tmp_path / "cache"
    cache.mkdir()
    destination = cache / bundle.asset
    destination.write_bytes(b"previous-cache-is-preserved")
    with pytest.raises((OSError, ValueError)):
        download_image_bundle(bundle, cache, base_url=archive_server.address)
    assert destination.read_bytes() == b"previous-cache-is-preserved"
    assert list(cache.iterdir()) == [destination]
