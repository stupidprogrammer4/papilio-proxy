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


def image_manifest(images: Path, version: str) -> tuple[bytes, dict[str, str]]:
    platforms: dict[str, object] = {}
    checksums: dict[str, str] = {}
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
            if bundle.format_version != 2:
                raise ValueError(
                    "Public image bundles must declare portable OCI and config identities."
                )
            if not archive_matches(images / bundle.asset, bundle):
                raise ValueError("The image archive size or checksum does not match its manifest.")
            normalized = bundle_manifest(bundle)["platforms"]
            if not isinstance(normalized, dict):
                raise ValueError("The normalized image platform manifest is invalid.")
            platforms.update(normalized)
            checksums[bundle.asset] = bundle.sha256
    manifest = {"format": 2, "version": version, "platforms": platforms}
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--images", type=Path)
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
    if arguments.images is not None:
        manifest, checksums = image_manifest(arguments.images, version)
    arguments.output.mkdir(parents=True, exist_ok=True)
    archive = arguments.output / f"papilio-{version}.tar.gz"
    source_archive(root, version, archive, manifest)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if arguments.images is not None:
        for name in checksums:
            source = arguments.images / name
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
