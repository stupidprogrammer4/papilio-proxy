"""Retain license texts for modules recorded in native Go build information."""

import json
import subprocess
from pathlib import Path
from typing import Any


def json_objects(content: str) -> tuple[dict[str, Any], ...]:
    decoder = json.JSONDecoder()
    remaining = content.lstrip()
    objects = []
    while remaining:
        value, end = decoder.raw_decode(remaining)
        if not isinstance(value, dict):
            raise ValueError("Native Go module metadata must contain JSON objects.")
        objects.append(value)
        remaining = remaining[end:].lstrip()
    return tuple(objects)


def dependency_notices(source: Path, binaries: tuple[Path, ...], destination: Path) -> Path:
    modules: set[str] = set()
    for binary in binaries:
        metadata = json.loads(
            subprocess.check_output(
                ["go", "version", "-m", "-json", str(binary)],
                text=True,
            )
        )
        for dependency in metadata.get("Deps", []):
            selected = dependency.get("Replace") or dependency
            version = selected.get("Version")
            if not version or version == "(devel)":
                raise ValueError(
                    "A local native dependency needs explicit source/license packaging."
                )
            modules.add(f"{selected['Path']}@{version}")
    downloaded = subprocess.check_output(
        ["go", "mod", "download", "-json", *sorted(modules)],
        cwd=source,
        text=True,
    )
    roots: list[tuple[str, Path]] = []
    for metadata in json_objects(downloaded):
        directory = metadata.get("Dir")
        if not isinstance(directory, str):
            raise ValueError("A native dependency source directory is missing.")
        roots.append((f"{metadata['Path']}@{metadata['Version']}", Path(directory)))
    goroot = Path(subprocess.check_output(["go", "env", "GOROOT"], text=True).strip())
    roots.append(("Go standard library", goroot))
    with destination.open("xb") as output:
        output.write(b"Native dependency license and notice texts\n")
        for name, directory in sorted(roots):
            notices = sorted(
                {
                    path
                    for pattern in ("LICENSE*", "LICENCE*", "COPYING*", "NOTICE*", "PATENTS*")
                    for path in directory.glob(pattern)
                    if path.is_file()
                }
            )
            if not notices:
                raise ValueError(f"The native dependency has no packaged root license: {name}")
            for notice in notices:
                output.write(f"\n===== {name} / {notice.name} =====\n".encode())
                output.write(notice.read_bytes())
                output.write(b"\n")
    return destination
