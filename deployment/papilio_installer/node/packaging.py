"""Build reproducible native node bundles from explicitly selected release inputs."""

import gzip
import hashlib
import io
import json
import tarfile
from dataclasses import asdict
from pathlib import Path

from .artifacts import NodeBundle, inspect_bundle


def write_bundle(
    destination: Path,
    version: str,
    selected_platform: str,
    agent: Path,
    xray: Path,
    papilio_license: Path,
    xray_license: Path,
    go_notices: Path,
) -> Path:
    inputs = {
        "bin/papilio-agent": agent,
        "bin/xray": xray,
        "licenses/Papilio-MIT.txt": papilio_license,
        "licenses/Xray-MPL-2.0.txt": xray_license,
        "licenses/Go-dependencies.txt": go_notices,
    }
    identities: dict[str, dict[str, str | int]] = {}
    for name, path in inputs.items():
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1048576), b""):
                digest.update(block)
        identities[name] = {"sha256": digest.hexdigest(), "size": path.stat().st_size}
    manifest = (
        json.dumps(
            {
                "format": 1,
                "version": version,
                "platform": selected_platform,
                "xray_version": "26.3.27",
                "files": identities,
            },
            sort_keys=True,
            indent=2,
        ).encode()
        + b"\n"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    output_file = destination.open("xb")
    try:
        with (
            output_file as output,
            gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as compressed,
            tarfile.open(fileobj=compressed, mode="w|") as archive,
        ):
            for name, path in sorted(inputs.items()):
                info = tarfile.TarInfo(name)
                info.mode = 0o755 if name.startswith("bin/") else 0o644
                info.size = path.stat().st_size
                with path.open("rb") as source:
                    archive.addfile(info, source)
            info = tarfile.TarInfo("manifest.json")
            info.mode = 0o644
            info.size = len(manifest)
            archive.addfile(info, io.BytesIO(manifest))
        inspect_bundle(destination, selected_platform)
    except (OSError, ValueError, tarfile.TarError):
        destination.unlink(missing_ok=True)
        raise
    return destination


def bundle_metadata(bundle: NodeBundle) -> dict[str, object]:
    return {
        "version": bundle.version,
        "platform": bundle.platform,
        "xray_version": bundle.xray_version,
        "files": {name: asdict(value) for name, value in bundle.files.items()},
    }
