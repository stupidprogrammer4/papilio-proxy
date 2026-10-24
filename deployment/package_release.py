#!/usr/bin/env python3
"""Package only the verified current commit, without local or uncommitted files."""

import argparse
import gzip
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from papilio_installer.image_build import bundle_manifest
from papilio_installer.images import PLATFORMS, archive_matches, read_image_bundle
from papilio_installer.node.artifacts import inspect_bundle


def image_manifest(
    images: Path, version: str, *, requires_node: bool = False
) -> tuple[bytes, dict[str, str]]:
    platforms: dict[str, object] = {}
    checksums: dict[str, str] = {}
    manifest_format: int | None = None
    with tempfile.TemporaryDirectory(prefix="papilio-manifest-") as temporary:
        root = Path(temporary)
        (root / "deployment").mkdir()
        (root / "VERSION").write_text(version)
        for platform in sorted(PLATFORMS):
            metadata = images / f"images-{platform.replace('/', '-')}.json"
            if not metadata.is_file():
                raise ValueError("A required image platform manifest is missing.")
            raw = json.loads(metadata.read_text())
            if not isinstance(raw, dict) or not isinstance(raw.get("platforms"), dict):
                raise ValueError("The image platform manifest has an invalid shape.")
            if set(raw["platforms"]) != {platform}:
                raise ValueError("Each image platform manifest must identify its own platform.")
            (root / "deployment/images.json").write_text(json.dumps(raw))
            bundle = read_image_bundle(root, platform)
            if bundle is None:
                raise ValueError("A required image platform manifest is missing.")
            if bundle.format_version not in {2, 3}:
                raise ValueError(
                    "Public image bundles must declare portable OCI and config identities."
                )
            if manifest_format is not None and manifest_format != bundle.format_version:
                raise ValueError("All image platforms must use the same manifest format.")
            if requires_node and bundle.format_version != 3:
                raise ValueError("This source release requires a portable node runtime image.")
            manifest_format = bundle.format_version
            if not archive_matches(images / bundle.asset, bundle):
                raise ValueError("The image archive size or checksum does not match its manifest.")
            normalized = bundle_manifest(bundle)["platforms"]
            if not isinstance(normalized, dict):
                raise ValueError("The normalized image platform manifest is invalid.")
            platforms.update(normalized)
            checksums[bundle.asset] = bundle.sha256
    manifest = {"format": manifest_format, "version": version, "platforms": platforms}
    return json.dumps(manifest, indent=2).encode() + b"\n", checksums


def source_archive(root: Path, version: str, destination: Path, manifest: bytes | None) -> None:
    result = subprocess.run(
        ["git", "archive", "--format=tar", f"--prefix=papilio-{version}/", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    with (
        destination.open("xb") as output,
        gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as compressed,
    ):
        if manifest is None:
            compressed.write(result.stdout)
            return
        member_name = f"papilio-{version}/deployment/images.json"
        with (
            tarfile.open(fileobj=io.BytesIO(result.stdout)) as original,
            tarfile.open(fileobj=compressed, mode="w|") as archive,
        ):
            if member_name in original.getnames():
                raise ValueError("The source commit already contains a generated image manifest.")
            for member in original:
                content = original.extractfile(member) if member.isfile() else None
                archive.addfile(member, content)
                if content is not None:
                    content.close()
            extra = tarfile.TarInfo(member_name)
            extra.mode = 0o644
            extra.size = len(manifest)
            archive.addfile(extra, io.BytesIO(manifest))


def node_checksums(nodes: Path, version: str) -> dict[str, str]:
    checksums = {}
    for platform in sorted(PLATFORMS):
        name = f"papilio-node-{version}-{platform.replace('/', '-')}.tar.gz"
        path = nodes / name
        if not path.is_file() or path.is_symlink():
            raise ValueError("A required node platform bundle is missing.")
        bundle = inspect_bundle(path, platform)
        if bundle.version != version:
            raise ValueError("The native node bundle does not match the selected release version.")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1048576), b""):
                digest.update(block)
        checksums[name] = digest.hexdigest()
    return checksums


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--images", type=Path)
    parser.add_argument("--nodes", type=Path)
    arguments = parser.parse_args()
    root = arguments.source.resolve()
    version = (root / "VERSION").read_text().strip()
    if arguments.tag != f"v{version}":
        raise ValueError("Release tag must match VERSION.")
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--"], cwd=root, check=True)
    # This source path belongs to the new Django implementation only.
    subprocess.run(
        ["git", "cat-file", "-e", "HEAD:panel/backend/src/papilio_panel/config/settings.py"],
        cwd=root,
        check=True,
    )
    manifest = None
    checksums = {}
    artifacts: dict[str, Path] = {}
    if arguments.images is not None:
        node_source = subprocess.run(
            ["git", "cat-file", "-e", "HEAD:deployment/node.Dockerfile"],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        manifest, checksums = image_manifest(
            arguments.images, version, requires_node=node_source.returncode == 0
        )
        artifacts.update({name: arguments.images / name for name in checksums})
    if arguments.nodes is not None:
        native_checksums = node_checksums(arguments.nodes, version)
        checksums.update(native_checksums)
        artifacts.update({name: arguments.nodes / name for name in native_checksums})
    arguments.output.mkdir(parents=True, exist_ok=True)
    archive = arguments.output / f"papilio-{version}.tar.gz"
    source_archive(root, version, archive, manifest)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    for name, source in artifacts.items():
        destination = arguments.output / name
        if source.resolve() != destination.resolve():
            with source.open("rb") as original, destination.open("xb") as output:
                shutil.copyfileobj(original, output, length=1024 * 1024)
    checksums[archive.name] = digest
    with (arguments.output / "SHA256SUMS").open("x") as output:
        output.write("".join(f"{digest}  {name}\n" for name, digest in sorted(checksums.items())))
    print(f"Packaged {archive.name} from the verified commit.")


if __name__ == "__main__":
    main()
