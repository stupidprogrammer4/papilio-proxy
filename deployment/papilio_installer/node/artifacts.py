"""Verify release-owned native executables before installation or execution."""

import hashlib
import json
import os
import platform
import re
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..releases import REPOSITORY, release_version

BUNDLE_FILES = frozenset(
    {
        "bin/papilio-agent",
        "bin/xray",
        "licenses/Papilio-MIT.txt",
        "licenses/Xray-MPL-2.0.txt",
        "licenses/Go-dependencies.txt",
    }
)
MACHINES = {"linux/amd64": 62, "linux/arm64": 183}


@dataclass(frozen=True)
class BundleFile:
    sha256: str
    size: int


@dataclass(frozen=True)
class NodeBundle:
    path: Path
    version: str
    platform: str
    xray_version: str
    files: dict[str, BundleFile]


def native_platform() -> str:
    architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
    if platform.system() != "Linux" or architecture is None:
        raise ValueError("Native node bundles currently target Linux amd64 and arm64.")
    return f"linux/{architecture}"


def executable_header(header: bytes, selected_platform: str) -> None:
    if (
        len(header) < 64
        or header[:6] != b"\x7fELF\x02\x01"
        or int.from_bytes(header[18:20], "little") != MACHINES[selected_platform]
    ):
        raise ValueError("A node executable does not match the declared Linux architecture.")


def inspect_bundle(
    path: Path, selected_platform: str, *, byte_limit: int = 536870912
) -> NodeBundle:
    if selected_platform not in MACHINES:
        raise ValueError("Choose a supported native node platform.")
    if type(byte_limit) is not int or byte_limit < 1 or path.stat().st_size > byte_limit:
        raise ValueError("The node bundle exceeds the configured byte limit.")
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        if (
            len(members) != len(BUNDLE_FILES) + 1
            or {member.name for member in members} != BUNDLE_FILES | {"manifest.json"}
            or sum(member.size for member in members) > byte_limit
            or any(not member.isfile() or member.size < 1 for member in members)
        ):
            raise ValueError("The node bundle contains missing, duplicate or unsafe members.")
        if archive.getmember("manifest.json").size > 65536:
            raise ValueError("The node manifest is missing or oversized.")
        manifest_file = archive.extractfile("manifest.json")
        if manifest_file is None:
            raise ValueError("The node manifest is missing.")
        with manifest_file:
            manifest = json.load(manifest_file)
        if (
            not isinstance(manifest, dict)
            or type(manifest.get("format")) is not int
            or manifest["format"] != 1
            or manifest.get("platform") != selected_platform
        ):
            raise ValueError("The node bundle format or platform does not match.")
        version = manifest.get("version")
        xray_version = manifest.get("xray_version")
        if (
            not isinstance(version, str)
            or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.]+)?", version) is None
            or not isinstance(xray_version, str)
            or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", xray_version) is None
        ):
            raise ValueError("The bundle version metadata is invalid.")
        metadata = manifest.get("files")
        if not isinstance(metadata, dict) or set(metadata) != BUNDLE_FILES:
            raise ValueError("Each native bundle file must have a declared identity.")
        verified: dict[str, BundleFile] = {}
        for member in members:
            if member.name == "manifest.json":
                continue
            declared = metadata[member.name]
            if (
                not isinstance(declared, dict)
                or type(declared.get("size")) is not int
                or declared["size"] != member.size
                or not isinstance(declared.get("sha256"), str)
                or re.fullmatch(r"[a-f0-9]{64}", declared["sha256"]) is None
            ):
                raise ValueError("The node bundle file identity is invalid.")
            content = archive.extractfile(member)
            if content is None:
                raise ValueError("A declared node bundle file is missing.")
            digest = hashlib.sha256()
            with content as stream:
                header = stream.read(64)
                digest.update(header)
                if PurePosixPath(member.name).parent.name == "bin":
                    executable_header(header, selected_platform)
                for block in iter(lambda: stream.read(1048576), b""):
                    digest.update(block)
            if digest.hexdigest() != declared["sha256"]:
                raise ValueError("A node bundle file checksum does not match.")
            verified[member.name] = BundleFile(declared["sha256"], member.size)
    return NodeBundle(path, version, selected_platform, xray_version, verified)


def download_bundle(
    source: Path, cache: Path, byte_limit: int, *, base_url: str | None = None
) -> Path:
    version = release_version((source / "VERSION").read_text().strip())
    filename = f"papilio-node-{version}-{native_platform().replace('/', '-')}.tar.gz"
    base = base_url or f"https://github.com/{REPOSITORY}/releases/download/v{version}"
    with urllib.request.urlopen(f"{base}/SHA256SUMS", timeout=30) as response:
        checksums = dict(
            (name, digest)
            for digest, name in (
                line.split() for line in response.read(1048576).decode().splitlines()
            )
        )
    expected = checksums.get(filename)
    if expected is None or re.fullmatch(r"[a-f0-9]{64}", expected) is None:
        raise ValueError("This release has no verified node bundle for the current platform.")
    if byte_limit < 1:
        raise ValueError("The bundle byte limit must be positive.")
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = cache / filename
    if destination.is_symlink():
        raise ValueError("A native bundle cache entry must not be a symbolic link.")
    if destination.is_file():
        if destination.stat().st_size > byte_limit:
            raise ValueError("The cached native bundle exceeds the configured byte limit.")
        digest = hashlib.sha256()
        with destination.open("rb") as stored:
            for block in iter(lambda: stored.read(1048576), b""):
                digest.update(block)
        if digest.hexdigest() == expected:
            return destination
        raise ValueError("The existing native bundle cache checksum has changed.")
    with tempfile.NamedTemporaryFile(dir=cache, delete=False) as output:
        temporary = Path(output.name)
        try:
            digest = hashlib.sha256()
            received = 0
            with urllib.request.urlopen(f"{base}/{filename}", timeout=90) as response:
                for block in iter(lambda: response.read(1048576), b""):
                    received += len(block)
                    if received > byte_limit:
                        raise ValueError("The node download exceeds the configured byte limit.")
                    output.write(block)
                    digest.update(block)
            if digest.hexdigest() != expected:
                raise ValueError("The downloaded native bundle checksum does not match.")
            output.flush()
            os.fsync(output.fileno())
            temporary.rename(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return destination
