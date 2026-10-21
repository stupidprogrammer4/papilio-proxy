"""Fetch immutable public release artifacts and validate their extraction."""

import hashlib
import json
import re
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

REPOSITORY = "stupidprogrammer4/papilio-proxy"


def release_version(raw: str) -> str:
    version = raw.removeprefix("v")
    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.]+)?", version) is None:
        raise ValueError("Invalid Papilio release version.")
    return version


def latest_version() -> str:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=20",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Papilio-installer"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        releases = json.load(response)
    available = (release for release in releases if not release["draft"])
    selected = next(available, None)
    if selected is None:
        raise ValueError("No published release is available.")
    return release_version(selected["tag_name"])


def extract_release(archive_path: Path, destination: Path, version: str) -> Path:
    version = release_version(version)
    root_name = f"papilio-{version}"
    seen = set()
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or path.parts[0] != root_name:
                raise ValueError("Unsafe release member path.")
            if not (member.isfile() or member.isdir()) or member.name in seen:
                raise ValueError("Release links, special files and duplicate members are rejected.")
            seen.add(member.name)
        root = destination / root_name
        if root.exists():
            raise FileExistsError("This release directory already exists.")
        destination.mkdir(parents=True, exist_ok=True)
        for member in members:
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("Missing release file contents.")
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
    if (root / "VERSION").read_text().strip() != version:
        raise ValueError("The source release version does not match the requested version.")
    return root


def download_release(home: Path, version: str | None = None) -> Path:
    selected = release_version(version) if version else latest_version()
    releases = home.resolve() / "releases"
    existing = releases / f"papilio-{selected}"
    if existing.exists():
        if (existing / "VERSION").read_text().strip() != selected:
            raise ValueError("Existing release metadata does not match.")
        return existing
    base = f"https://github.com/{REPOSITORY}/releases/download/v{selected}"
    filename = f"papilio-{selected}.tar.gz"
    with tempfile.TemporaryDirectory(prefix="papilio-download-") as temporary:
        archive = Path(temporary) / filename
        with (
            urllib.request.urlopen(f"{base}/{filename}", timeout=60) as response,
            archive.open("wb") as output,
        ):
            shutil.copyfileobj(response, output)
        with urllib.request.urlopen(f"{base}/SHA256SUMS", timeout=30) as response:
            checksums = response.read().decode().splitlines()
        entries = {
            name.lstrip("*"): digest for digest, name in (line.split() for line in checksums)
        }
        digest = hashlib.sha256()
        with archive.open("rb") as archive_stream:
            for block in iter(lambda: archive_stream.read(1024 * 1024), b""):
                digest.update(block)
        if entries.get(filename) != digest.hexdigest():
            raise ValueError("The downloaded release checksum does not match.")
        release_source = extract_release(archive, releases, selected)
    return release_source
