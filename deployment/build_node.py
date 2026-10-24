#!/usr/bin/env python3
"""Build a native agent and package it with the pinned, verified official Xray."""

import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from papilio_installer.node.artifacts import native_platform
from papilio_installer.node.notices import dependency_notices
from papilio_installer.node.packaging import write_bundle
from papilio_installer.releases import release_version

XRAY_VERSION = "26.3.27"
OFFICIAL_ARCHIVES = {
    "linux/amd64": (
        "Xray-linux-64.zip",
        "23cd9af937744d97776ee35ecad4972cf4b2109d1e0fe6be9930467608f7c8ae",
    ),
    "linux/arm64": (
        "Xray-linux-arm64-v8a.zip",
        "4d30283ae614e3057f730f67cd088a42be6fdf91f8639d82cb69e48cde80413c",
    ),
}


def official_xray(cache: Path, selected_platform: str) -> tuple[Path, Path]:
    filename, expected = OFFICIAL_ARCHIVES[selected_platform]
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    archive_path = cache / filename
    if not archive_path.exists():
        address = f"https://github.com/XTLS/Xray-core/releases/download/v{XRAY_VERSION}/{filename}"
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as output:
            temporary = Path(output.name)
            try:
                with urllib.request.urlopen(address, timeout=90) as response:
                    shutil.copyfileobj(response, output, length=1048576)
                output.flush()
                os.fsync(output.fileno())
                temporary.rename(archive_path)
            finally:
                temporary.unlink(missing_ok=True)
    digest = hashlib.sha256()
    with archive_path.open("rb") as source:
        for block in iter(lambda: source.read(1048576), b""):
            digest.update(block)
    if digest.hexdigest() != expected:
        raise ValueError("The official Xray archive checksum does not match the pinned release.")
    with zipfile.ZipFile(archive_path) as archive:
        for name in ("xray", "LICENSE"):
            with archive.open(name) as source, (cache / name).open("wb") as output:
                shutil.copyfileobj(source, output, length=1048576)
    (cache / "xray").chmod(0o755)
    return cache / "xray", cache / "LICENSE"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--cache", type=Path)
    arguments = parser.parse_args()
    source = arguments.source.resolve()
    selected_platform = native_platform()
    version = release_version((source / "VERSION").read_text().strip())
    cache = arguments.cache or arguments.output / ".build-cache"
    xray, xray_license = official_xray(cache.resolve(), selected_platform)
    with tempfile.TemporaryDirectory(prefix="papilio-node-build-") as temporary:
        agent = Path(temporary) / "papilio-agent"
        subprocess.run(
            ["go", "build", "-trimpath", "-ldflags=-s -w", "-o", str(agent), "./cmd/papilio-agent"],
            cwd=source / "node/agent",
            env=os.environ | {"CGO_ENABLED": "0"},
            check=True,
        )
        destination = (
            arguments.output
            / f"papilio-node-{version}-{selected_platform.replace('/', '-')}.tar.gz"
        )
        notices = dependency_notices(
            source / "node/agent", (agent, xray), Path(temporary) / "Go-dependencies.txt"
        )
        write_bundle(
            destination,
            version,
            selected_platform,
            agent,
            xray,
            source / "LICENSE",
            xray_license,
            notices,
        )
    print(f"Built {destination.name} with native executables and retained license notices.")


if __name__ == "__main__":
    main()
